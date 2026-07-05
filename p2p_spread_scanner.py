#!/usr/bin/env python3
"""
P2P Spread Scanner — версия для GitHub Actions (один прогон и выход).

Читает публичные P2P-цены USDT/RUB на биржах, считает разрыв между
лучшей ценой покупки на одной площадке и продажей на другой, и если
спред превышает порог — шлёт алерт в Telegram. Затем завершается.

Токен и chat_id берутся из переменных окружения (GitHub Secrets),
а НЕ из кода. Так их не видно даже в публичном репозитории.

Бот только читает цены и шлёт алерт. Деньгами и сделками не управляет.
"""

import os
import requests

# ─────────────────────────── НАСТРОЙКИ ───────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ASSET = "USDT"
FIAT = "RUB"

MIN_SPREAD_PCT = 1.5      # слать алерт, если спред >= этого %
NETWORK_FEE_USDT = 1.0    # комиссия перегона между биржами (TRC-20 ~1 USDT)
TRADE_AMOUNT_RUB = 100000 # объём для оценки прибыли в рублях
PAYMENTS = []             # ID методов оплаты (пусто = все)

# Какие биржи мониторить
ENABLED = {
    "bybit":  True,
    "mexc":   False,   # впишите эндпоинт в fetch_mexc и включите
    "bingx":  False,
    "kucoin": False,
    "htx":    False,
    "bitget": False,
    "gate":   False,
}

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

# ─────────────────────── ФЕТЧЕРЫ ПО БИРЖАМ ───────────────────────
# Возвращают (best_buy, best_sell):
#   best_buy  — мин. цена, по которой ВЫ можете КУПИТЬ USDT
#   best_sell — макс. цена, по которой ВЫ можете ПРОДАТЬ USDT
# При ошибке — None, биржа пропускается.

def fetch_bybit():
    url = "https://api2.bybit.com/fiat/otc/item/online"

    def query(side):
        # Проверьте направление side на живых данных и при необходимости
        # поменяйте "0"/"1" местами.
        # side "1" — мерчант ПРОДАЁТ USDT (вы покупаете)
        # side "0" — мерчант ПОКУПАЕТ USDT (вы продаёте)
        payload = {
            "tokenId": ASSET, "currencyId": FIAT, "side": side,
            "size": "10", "page": "1", "payment": PAYMENTS,
        }
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        items = r.json()["result"]["items"]
        return [float(i["price"]) for i in items if i.get("price")]

    asks = query("1")
    bids = query("0")
    if not asks or not bids:
        return None
    return min(asks), max(bids)


def fetch_mexc():
    # TODO: впишите P2P-эндпоинт MEXC по образцу fetch_bybit.
    raise NotImplementedError("Добавьте эндпоинт MEXC")


def fetch_bingx():  raise NotImplementedError("Добавьте эндпоинт BingX")
def fetch_kucoin(): raise NotImplementedError("Добавьте эндпоинт KuCoin")
def fetch_htx():    raise NotImplementedError("Добавьте эндпоинт HTX")
def fetch_bitget(): raise NotImplementedError("Добавьте эндпоинт Bitget")
def fetch_gate():   raise NotImplementedError("Добавьте эндпоинт Gate")

FETCHERS = {
    "bybit": fetch_bybit, "mexc": fetch_mexc, "bingx": fetch_bingx,
    "kucoin": fetch_kucoin, "htx": fetch_htx, "bitget": fetch_bitget,
    "gate": fetch_gate,
}

# ──────────────────────────── TELEGRAM ───────────────────────────
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Нет TELEGRAM_TOKEN/CHAT_ID в секретах — сообщение не отправлено.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=15)
    except Exception as e:
        print("Telegram error:", e)

# ──────────────────────────── ЛОГИКА ─────────────────────────────
def collect_quotes():
    quotes = {}
    for name, on in ENABLED.items():
        if not on:
            continue
        try:
            res = FETCHERS[name]()
            if res:
                buy, sell = res
                quotes[name] = {"buy": buy, "sell": sell}
        except NotImplementedError as e:
            print(f"[{name}] {e}")
        except Exception as e:
            print(f"[{name}] ошибка запроса: {e}")
    return quotes


def find_best_spread(quotes):
    if len(quotes) < 1:
        return None
    buy_ex = min(quotes, key=lambda x: quotes[x]["buy"])
    sell_ex = max(quotes, key=lambda x: quotes[x]["sell"])
    if buy_ex == sell_ex and len(quotes) > 1:
        return None
    buy_price = quotes[buy_ex]["buy"]
    sell_price = quotes[sell_ex]["sell"]
    usdt = TRADE_AMOUNT_RUB / buy_price
    rub_out = (usdt - NETWORK_FEE_USDT) * sell_price
    profit_rub = rub_out - TRADE_AMOUNT_RUB
    return {
        "buy_ex": buy_ex, "buy_price": buy_price,
        "sell_ex": sell_ex, "sell_price": sell_price,
        "spread_pct": profit_rub / TRADE_AMOUNT_RUB * 100,
        "profit_rub": profit_rub,
    }


def main():
    quotes = collect_quotes()
    best = find_best_spread(quotes)
    if not best:
        print("Нет данных / недостаточно бирж.")
        return
    print(f"{best['buy_ex']} buy {best['buy_price']:.2f} → "
          f"{best['sell_ex']} sell {best['sell_price']:.2f} | "
          f"спред {best['spread_pct']:.2f}%")
    if best["spread_pct"] >= MIN_SPREAD_PCT:
        send_telegram(
            f"⚡ <b>Спред {best['spread_pct']:.2f}%</b>\n"
            f"Купить: <b>{best['buy_ex']}</b> по {best['buy_price']:.2f} ₽\n"
            f"Продать: <b>{best['sell_ex']}</b> по {best['sell_price']:.2f} ₽\n"
            f"Оценка прибыли на {TRADE_AMOUNT_RUB:,} ₽: ~{best['profit_rub']:,.0f} ₽"
        )


if __name__ == "__main__":
    main()
