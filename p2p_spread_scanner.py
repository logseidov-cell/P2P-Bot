import os
import json
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ASSET = "USDT"
FIAT = "RUB"
MIN_SPREAD_PCT = 1.5
NETWORK_FEE_USDT = 1.0
TRADE_AMOUNT_RUB = 100000

DEBUG_MEXC = True  # печатать сырой ответ MEXC в лог (для настройки)

ENABLED = {
    "bybit": True,
    "mexc":  True,
}

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def fetch_bybit():
    url = "https://api2.bybit.com/fiat/otc/item/online"

    def query(side):
        payload = {"tokenId": ASSET, "currencyId": FIAT, "side": side,
                   "size": "10", "page": "1", "payment": []}
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        items = r.json()["result"]["items"]
        return [float(i["price"]) for i in items if i.get("price")]

    asks = query("1")
    bids = query("0")
    if not asks or not bids:
        return None
    return min(asks), max(bids)


def fetch_mexc():
    # tradeType: BUY = вы покупаете USDT, SELL = вы продаёте
    url = "https://p2p.mexc.com/api/market/otc/ads/list"

    def query(trade_type):
        params = {
            "currency": ASSET, "fiat": FIAT, "tradeType": trade_type,
            "page": "1", "pageSize": "10",
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if DEBUG_MEXC:
            print(f"=== MEXC raw ({trade_type}) ===")
            print(json.dumps(data, ensure_ascii=False)[:1500])
        # структуру уточним по выводу; пробуем типовой путь
        items = data.get("data", []) or []
        prices = []
        for it in items:
            p = it.get("price") or it.get("adv", {}).get("price")
            if p:
                prices.append(float(p))
        return prices

    asks = query("BUY")
    bids = query("SELL")
    if not asks or not bids:
        return None
    return min(asks), max(bids)


FETCHERS = {"bybit": fetch_bybit, "mexc": fetch_mexc}


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Нет секретов Telegram.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                                 "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print("Telegram error:", e)


def collect_quotes():
    quotes = {}
    for name, on in ENABLED.items():
        if not on:
            continue
        try:
            res = FETCHERS[name]()
            if res:
                quotes[name] = {"buy": res[0], "sell": res[1]}
                print(f"[{name}] buy={res[0]} sell={res[1]}")
            else:
                print(f"[{name}] нет данных")
        except Exception as e:
            print(f"[{name}] ошибка: {e}")
    return quotes


def find_best_spread(quotes):
    if len(quotes) < 1:
        return None
    buy_ex = min(quotes, key=lambda x: quotes[x]["buy"])
    sell_ex = max(quotes, key=lambda x: quotes[x]["sell"])
    if buy_ex == sell_ex and len(quotes) > 1:
        return None
    bp = quotes[buy_ex]["buy"]
    sp = quotes[sell_ex]["sell"]
    usdt = TRADE_AMOUNT_RUB / bp
    profit = (usdt - NETWORK_FEE_USDT) * sp - TRADE_AMOUNT_RUB
    return {"buy_ex": buy_ex, "buy_price": bp, "sell_ex": sell_ex,
            "sell_price": sp, "spread_pct": profit / TRADE_AMOUNT_RUB * 100,
            "profit_rub": profit}


def main():
    quotes = collect_quotes()
    best = find_best_spread(quotes)
    if not best:
        print("Итог: нет данных для сравнения.")
        return
    print(f"ЛУЧШЕЕ: {best['buy_ex']} {best['buy_price']:.2f} -> "
          f"{best['sell_ex']} {best['sell_price']:.2f} | {best['spread_pct']:.2f}%")
    if best["spread_pct"] >= MIN_SPREAD_PCT:
        send_telegram(
            f"⚡ Спред {best['spread_pct']:.2f}%\n"
            f"Купить: {best['buy_ex']} по {best['buy_price']:.2f} ₽\n"
            f"Продать: {best['sell_ex']} по {best['sell_price']:.2f} ₽\n"
            f"Прибыль на {TRADE_AMOUNT_RUB:,} ₽: ~{best['profit_rub']:,.0f} ₽")


if __name__ == "__main__":
    main()
