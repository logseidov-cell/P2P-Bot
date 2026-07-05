import os
import statistics
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

ASSET = "USDT"
FIAT = "RUB"

# ── ВАШИ ГРАНИЦЫ (меняйте под себя) ──
BUY_BELOW = 76.0      # алерт, если где-то можно КУПИТЬ USDT дешевле этой цены
SELL_ABOVE = 79.0     # алерт, если где-то можно ПРОДАТЬ USDT дороже этой цены
MIN_SPREAD_PCT = 1.0  # алерт, если межбиржевой спред >= этого %
# ─────────────────────────────────────

NETWORK_FEE_USDT = 1.0
TRADE_AMOUNT_RUB = 100000
OUTLIER_PCT = 3.0

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def clean(prices):
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return prices
    med = statistics.median(prices)
    return [p for p in prices if abs(p - med) / med * 100 <= OUTLIER_PCT]


def fetch_bybit():
    url = "https://api2.bybit.com/fiat/otc/item/online"
    def q(side):
        r = requests.post(url, json={"tokenId": ASSET, "currencyId": FIAT,
            "side": side, "size": "20", "page": "1", "payment": []},
            headers=HEADERS, timeout=15)
        return [float(i["price"]) for i in r.json()["result"]["items"] if i.get("price")]
    a, b = clean(q("1")), clean(q("0"))
    return (min(a), max(b)) if a and b else None


def fetch_binance():
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    def q(t):
        r = requests.post(url, json={"asset": ASSET, "fiat": FIAT,
            "tradeType": t, "page": 1, "rows": 20, "payTypes": [],
            "publisherType": None}, headers=HEADERS, timeout=15)
        return [float(x["adv"]["price"]) for x in r.json().get("data", [])
                if x.get("adv", {}).get("price")]
    a, b = clean(q("BUY")), clean(q("SELL"))
    return (min(a), max(b)) if a and b else None


def fetch_htx():
    url = "https://otc-akm.huobi.com/v1/otc/trade/list/public"
    def q(trade):  # trade: 1 = продавцы (вы покупаете), 0 = покупатели (вы продаёте)
        params = {"coinId": 2, "currency": 11, "tradeType": trade,
                  "currPage": 1, "payMethod": 0, "country": "", "blockType": "general",
                  "online": 1, "range": 0, "amount": "", "isFollowed": "false"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        return [float(x["price"]) for x in r.json().get("data", []) if x.get("price")]
    a, b = clean(q(1)), clean(q(0))
    return (min(a), max(b)) if a and b else None


def fetch_okx():
    url = "https://www.okx.com/v3/c2c/tradingOrders/books"
    def q(side):  # side: sell = мерчант продаёт (вы покупаете), buy = наоборот
        params = {"quoteCurrency": FIAT, "baseCurrency": ASSET, "side": side,
                  "paymentMethod": "all", "userType": "all", "showTrade": "false"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        d = r.json().get("data", {})
        rows = d.get("sell", []) + d.get("buy", []) if isinstance(d, dict) else []
        return [float(x["price"]) for x in rows if x.get("price")]
    a, b = clean(q("sell")), clean(q("buy"))
    return (min(a), max(b)) if a and b else None


FETCHERS = {"bybit": fetch_bybit, "binance": fetch_binance,
            "htx": fetch_htx, "okx": fetch_okx}


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Нет секретов Telegram.")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
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

    if not quotes:
        print("Ни одна биржа не ответила.")
        return

    alerts = []

    # 1) Ценовые границы по каждой бирже
    for name, q in quotes.items():
        if q["buy"] <= BUY_BELOW:
            alerts.append(f"🟢 {name}: купить по {q['buy']:.2f} ₽ (ниже {BUY_BELOW})")
        if q["sell"] >= SELL_ABOVE:
            alerts.append(f"🔵 {name}: продать по {q['sell']:.2f} ₽ (выше {SELL_ABOVE})")

    # 2) Межбиржевой спред (только между разными биржами)
    if len(quotes) >= 2:
        best = None
        for bex in quotes:
            for sex in quotes:
                if bex == sex:
                    continue
                bp, sp = quotes[bex]["buy"], quotes[sex]["sell"]
                usdt = TRADE_AMOUNT_RUB / bp
                profit = (usdt - NETWORK_FEE_USDT) * sp - TRADE_AMOUNT_RUB
                pct = profit / TRADE_AMOUNT_RUB * 100
                if best is None or pct > best["pct"]:
                    best = {"bex": bex, "bp": bp, "sex": sex, "sp": sp,
                            "pct": pct, "profit": profit}
        print(f"Лучший спред: {best['bex']} {best['bp']:.2f} -> "
              f"{best['sex']} {best['sp']:.2f} | {best['pct']:.2f}%")
        if best["pct"] >= MIN_SPREAD_PCT:
            alerts.append(
                f"⚡ Спред {best['pct']:.2f}%: купить {best['bex']} {best['bp']:.2f} ₽ "
                f"→ продать {best['sex']} {best['sp']:.2f} ₽ "
                f"(~{best['profit']:,.0f} ₽ на {TRADE_AMOUNT_RUB:,})")

    if alerts:
        send_telegram("\n".join(alerts))
        print("Отправлено алертов:", len(alerts))
    else:
        print("Условия алерта не сработали (это норма).")


if __name__ == "__main__":
    main()
