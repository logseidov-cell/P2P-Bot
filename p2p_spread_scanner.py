import os
import statistics
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ASSET = "USDT"
FIAT = "RUB"
MIN_SPREAD_PCT = 1.0        # порог алерта (можно менять)
NETWORK_FEE_USDT = 1.0
TRADE_AMOUNT_RUB = 100000
OUTLIER_PCT = 3.0           # отбрасывать цены дальше 3% от медианы

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def clean(prices):
    """Убирает фантомные цены — всё, что дальше OUTLIER_PCT от медианы."""
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return prices
    med = statistics.median(prices)
    return [p for p in prices if abs(p - med) / med * 100 <= OUTLIER_PCT]


def fetch_bybit():
    url = "https://api2.bybit.com/fiat/otc/item/online"

    def query(side):
        payload = {"tokenId": ASSET, "currencyId": FIAT, "side": side,
                   "size": "20", "page": "1", "payment": []}
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        items = r.json()["result"]["items"]
        return [float(i["price"]) for i in items if i.get("price")]

    asks = clean(query("1"))   # где вы покупаете
    bids = clean(query("0"))   # где вы продаёте
    if not asks or not bids:
        return None
    return min(asks), max(bids)


def fetch_binance():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

    def query(trade_type):
        payload = {"asset": ASSET, "fiat": FIAT, "tradeType": trade_type,
                   "page": 1, "rows": 20, "payTypes": [],
                   "publisherType": None}
        r = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        rows = r.json().get("data", [])
        return [float(x["adv"]["price"]) for x in rows if x.get("adv", {}).get("price")]

    asks = clean(query("BUY"))
    bids = clean(query("SELL"))
    if not asks or not bids:
        return None
    return min(asks), max(bids)


FETCHERS = {"bybit": fetch_bybit, "binance": fetch_binance}


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Нет секретов Telegram.")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15)
    except Exception as e:
        print("Telegram error:", e)


def main():
    quotes = {}
    for name, fn in FETCHERS.items():
        try:
            res = fn()
            if res:
                quotes[name] = {"buy": res[0], "sell": res[1]}
                print(f"[{name}] buy={res[0]:.2f} sell={res[1]:.2f}")
            else:
                print(f"[{name}] нет данных")
        except Exception as e:
            print(f"[{name}] ошибка: {e}")

    if len(quotes) < 2:
        print("Недостаточно бирж для сравнения (нужно 2+).")
        return

    best = None
    for bex in quotes:
        for sex in quotes:
            if bex == sex:               # запрет сравнивать биржу саму с собой
                continue
            bp = quotes[bex]["buy"]
            sp = quotes[sex]["sell"]
            usdt = TRADE_AMOUNT_RUB / bp
            profit = (usdt - NETWORK_FEE_USDT) * sp - TRADE_AMOUNT_RUB
            pct = profit / TRADE_AMOUNT_RUB * 100
            if best is None or pct > best["pct"]:
                best = {"bex": bex, "bp": bp, "sex": sex, "sp": sp,
                        "pct": pct, "profit": profit}

    print(f"ЛУЧШЕЕ: {best['bex']} {best['bp']:.2f} -> "
          f"{best['sex']} {best['sp']:.2f} | {best['pct']:.2f}%")
    if best["pct"] >= MIN_SPREAD_PCT:
        send_telegram(
            f"⚡ Спред {best['pct']:.2f}%\n"
            f"Купить: {best['bex']} по {best['bp']:.2f} ₽\n"
            f"Продать: {best['sex']} по {best['sp']:.2f} ₽\n"
            f"Прибыль на {TRADE_AMOUNT_RUB:,} ₽: ~{best['profit']:,.0f} ₽")


if __name__ == "__main__":
    main()
