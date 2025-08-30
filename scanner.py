import os
import time
import requests
from datetime import datetime
import random

# --- Configuration ---
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")
VOL_X = float(os.getenv("VOLUME_MULTIPLIER", "1.1"))  # multiplier from secrets
UA = {"User-Agent": "crypto-volume-scanner/1.0 (+https://github.com/rahuliniyan)"}

# --- API endpoints ---
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
BN_EXINFO = "https://api.binance.com/api/v3/exchangeInfo"
BN_KLINES = "https://api.binance.com/api/v3/klines"

# --- Helpers ---
def req_json(url, params=None, max_retries=3, base_sleep=0.5):
    for i in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 429:
                sleep = base_sleep * (2 ** i) + random.uniform(0, 0.5)
                print(f"[429] Rate limited. Sleeping {sleep:.2f}s")
                time.sleep(sleep)
                continue
            if r.status_code >= 500:
                sleep = base_sleep * (2 ** i)
                print(f"[{r.status_code}] Server error. Retrying {sleep:.2f}s")
                time.sleep(sleep)
                continue
            if r.status_code != 200:
                print(f"[Error] {url} → {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            sleep = base_sleep * (2 ** i)
            print(f"[Exception] {url}: {e}, retrying {sleep:.2f}s")
            time.sleep(sleep)
    return None

def get_top200():
    params = {"vs_currency":"usd", "order":"market_cap_desc", "per_page":200, "page":1, "sparkline":"false"}
    return req_json(CG_MARKETS, params) or []

def get_usdt_symbols():
    data = req_json(BN_EXINFO)
    syms = set()
    if isinstance(data, dict):
        for s in data.get("symbols", []):
            if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT":
                syms.add(s.get("symbol"))
    return syms

def get_klines(symbol):
    return req_json(BN_KLINES, {"symbol": symbol, "interval": "5m", "limit":31})

def sma(vals):
    return sum(vals)/len(vals) if vals else 0.0

def tg_send(text):
    if not TG_TOKEN or not TG_CHAT:
        print("❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":TG_CHAT, "text":text, "parse_mode":"HTML"},
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
    print(f"== Scan started at {now} ==")

    coins = get_top200()
    if not coins:
        print("❌ Failed to get top200 coins")
        return 0

    usdt_pairs = get_usdt_symbols()
    if not usdt_pairs:
        print("❌ Failed to get Binance USDT pairs")
        return 0

    scanned = 0
    alerts_sent = 0
    test_alert_sent = False

    for c in coins:
        base = (c.get("symbol") or "").upper()
        if base in ("USDT","USDC","BUSD","DAI","FRAX"):
            continue
        pair = f"{base}USDT"
        if pair not in usdt_pairs:
            continue

        klines = get_klines(pair)
        time.sleep(0.05)
        if not isinstance(klines, list) or len(klines)<31:
            continue

        volumes = [float(k[5]) for k in klines]
        avg30 = sma(volumes[-31:-1])
        curr = volumes[-2]  # last closed candle
        scanned += 1

        ratio = curr/avg30 if avg30 else 0.0

        # --- Test alert for first scanned coin ---
        if not test_alert_sent:
            price = c.get("current_price",0)
            chg24 = c.get("price_change_percentage_24h",0) or 0.0
            msg = (
                f"✅ TEST ALERT: Scanned 1 coin\n"
                f"• Coin: <b>{c.get('name','')} ({base})</b>\n"
                f"• Pair: <b>{pair}</b>\n"
                f"• Price: ${price:.6f}\n"
                f"• 24h Change: {chg24:.2f}%\n"
                f"• Last candle volume: {curr:.2f}\n"
                f"• Avg30: {avg30:.2f}\n"
                f"• Time: {now}"
            )
            tg_send(msg)
            print("✅ Test alert sent")
            test_alert_sent = True
            alerts_sent += 1

        # --- Real Telegram alerts ---
        if avg30>0 and curr >= VOL_X*avg30:
            price = c.get("current_price",0)
            chg24 = c.get("price_change_percentage_24h",0) or 0.0
            msg = (
                f"🚨 <b>5m Volume Spike</b>\n"
                f"• Coin: <b>{c.get('name','')} ({base})</b>\n"
                f"• Pair: <b>{pair}</b>\n"
                f"• Price: ${price:.6f}\n"
                f"• 24h Change: {chg24:.2f}%\n"
                f"• Spike: <b>{ratio:.2f}×</b>\n"
                f"• Time: {now}"
            )
            tg_send(msg)
            alerts_sent += 1
            print(f"🚨 ALERT sent for {pair} (ratio {ratio:.2f}x)")

    print(f"== Scan completed: scanned={scanned}, alerts sent={alerts_sent} ==")
    return 0

if __name__=="__main__":
    main()
