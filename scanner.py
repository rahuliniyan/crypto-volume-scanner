import os
import time
import requests
from datetime import datetime
import random

# --- Config ---
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")
VOL_X = float(os.getenv("VOLUME_MULTIPLIER", "1.1"))  # 1.1x for testing
UA = {"User-Agent": "crypto-volume-scanner/1.0 (+https://github.com/rahuliniyan)"}

# --- API Endpoints ---
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
BN_EXINFO = "https://api.binance.com/api/v3/exchangeInfo"
BN_KLINES = "https://api.binance.com/api/v3/klines"

# --- Helpers ---
def req_json(url, params=None, max_retries=3, base_sleep=0.6):
    for i in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 429:
                sleep = base_sleep * (2 ** i) + random.uniform(0, 0.5)
                print(f"[429] Rate limited. Sleep {sleep:.2f}s")
                time.sleep(sleep)
                continue
            if r.status_code >= 500:
                sleep = base_sleep * (2 ** i)
                print(f"[{r.status_code}] Server error. Retry {sleep:.2f}s")
                time.sleep(sleep)
                continue
            if r.status_code != 200:
                print(f"[Error] {url} → {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            print(f"[Exception] {url}: {e}")
            time.sleep(base_sleep * (2 ** i))
    return None

def get_top200():
    params = {"vs_currency": "usd", "order": "market_cap_desc",
              "per_page": 200, "page": 1, "sparkline": "false"}
    return req_json(CG_MARKETS, params) or []

def get_usdt_symbols():
    data = req_json(BN_EXINFO, {"permissions": "SPOT"})
    syms = set()
    if isinstance(data, dict):
        for s in data.get("symbols", []):
            if (s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"
                and s.get("isSpotTradingAllowed", True)):
                syms.add(s.get("symbol"))
    return syms

def get_klines(symbol):
    return req_json(BN_KLINES, {"symbol": symbol, "interval": "5m", "limit": 31})

def sma(vals):
    return sum(vals)/len(vals) if vals else 0.0

def tg_send(text):
    if not TG_TOKEN or not TG_CHAT:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=20
        )
        if r.status_code != 200:
            print(f"Telegram send failed {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Telegram exception: {e}")
        return False

# --- Main Scanner ---
def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"== Scan start {now} ==")

    coins = get_top200()
    if not coins:
        print("No top200 data; exiting")
        return 0

    usdt = get_usdt_symbols()
    if not usdt:
        print("No Binance USDT pairs; exiting")
        return 0

    scanned = 0
    alerts = 0

    for c in coins:
        base = (c.get("symbol") or "").upper()
        if base in ("USDT","USDC","BUSD","DAI","FRAX","TUSD"):
            continue
        pair = f"{base}USDT"
        if pair not in usdt:
            continue

        kls = get_klines(pair)
        time.sleep(0.05)
        if not isinstance(kls, list) or len(kls) < 31:
            continue

        # Only use closed candles
        vols = [float(row[5]) for row in kls]
        avg30 = sma(vols[-31:-1])  # last 30 closed
        curr  = vols[-2]           # most recent closed candle

        scanned += 1
        ratio = curr / avg30 if avg30 else 0.0

        print(f"{pair}: curr={curr:.2f}, avg30={avg30:.2f}, ratio={ratio:.2f}x")

        if avg30 > 0 and curr >= VOL_X * avg30:
            price = c.get("current_price",0.0)
            chg24 = c.get("price_change_percentage_24h",0.0) or 0.0
            msg = (
                f"🚨 <b>5m Volume Spike</b>\n"
                f"• Coin: <b>{c.get('name','')} ({base})</b>\n"
                f"• Pair: <b>{pair}</b>\n"
                f"• Price: ${price:.6f}\n"
                f"• 24h Change: {chg24:.2f}%\n"
                f"• Spike: <b>{ratio:.2f}×</b> normal\n"
                f"• Time: {now}"
            )
            tg_send(msg)
            alerts += 1
            print(f"Alert sent for {pair}!")

    # Force test alert once per run to verify Telegram
    tg_send(f"✅ Test alert: Scanner run completed at {now}")

    print(f"== Scan done: scanned={scanned}, alerts={alerts} ==")
    return 0

if __name__ == "__main__":
    exit(main())

