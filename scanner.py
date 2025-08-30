import os, time, math, json, random, requests, sys
from datetime import datetime

# --- Config from environment ---
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID")
VOL_X    = float(os.getenv("VOLUME_MULTIPLIER", "2.0"))

# --- API endpoints ---
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
BN_EXINFO  = "https://api.binance.com/api/v3/exchangeInfo"
BN_KLINES  = "https://api.binance.com/api/v3/klines"

UA = {"User-Agent": "volume-scanner/1.0 (+https://github.com/)"}

# --- Helpers ---
def req_json(url, params=None, max_retries=4, base_sleep=0.6):
    for i in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            if r.status_code == 429:
                sleep = base_sleep * (2 ** i) + random.uniform(0, 0.5)
                print(f"[{url}] 429 rate limited, sleeping {sleep:.2f}s")
                time.sleep(sleep); continue
            if r.status_code >= 500:
                sleep = base_sleep * (2 ** i)
                print(f"[{url}] {r.status_code} server error, retry in {sleep:.2f}s")
                time.sleep(sleep); continue
            if r.status_code != 200:
                print(f"[{url}] HTTP {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            sleep = base_sleep * (2 ** i)
            print(f"[{url}] Exception {e}, retry in {sleep:.2f}s")
            time.sleep(sleep)
    return None

def get_top500():
    coins = []
    for page in (1, 2):
        params = {"vs_currency":"usd","order":"market_cap_desc","per_page":250,"page":page,"sparkline":"false"}
        data = req_json(CG_MARKETS, params)
        if not isinstance(data, list):
            print(f"CoinGecko page {page} failed; skipping")
            continue
        coins.extend(data)
        time.sleep(0.2)
    return coins

def get_usdt_symbols():
    data = req_json(BN_EXINFO, {"permissions":"SPOT"})
    syms = set()
    if isinstance(data, dict):
        for s in data.get("symbols", []):
            if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT" and s.get("isSpotTradingAllowed", True):
                syms.add(s.get("symbol"))
    if not syms:
        print("Binance exchangeInfo returned no USDT symbols")
    return syms

def get_klines(symbol):
    return req_json(BN_KLINES, {"symbol":symbol,"interval":"5m","limit":31})

def sma(vals): 
    return sum(vals)/len(vals) if vals else 0.0

def tg_send(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":TG_CHAT,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},
            timeout=20
        )
        if r.status_code != 200:
            print(f"Telegram send failed {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"Telegram exception: {e}")
        return False

# --- Main ---
def main():
    if not TG_TOKEN or not TG_CHAT:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return 1

    # --- Test mode ---
    if "--test" in sys.argv:
        print("Running in test mode — sending dummy alert")
        tg_send("🚨 TEST ALERT: Bot is working ✅")
        return 0

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"== Scan start {now} ==")

    coins = get_top500()
    if not coins:
        print("No top500 data; exiting gracefully")
        return 0

    usdt = get_usdt_symbols()
    if not usdt:
        print("No Binance USDT symbols; exiting gracefully")
        return 0

    scanned = 0; alerts = 0
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

        # ✅ FIX: use row[5] (volume)
        vols = [float(row[5]) for row in kls]
        avg30 = sma(vols[-31:-1])
        curr = vols[-1]
        scanned += 1

        if avg30 > 0 and curr > VOL_X * avg30:
            ratio = curr / avg30
            price = c.get("current_price", 0.0)
            chg24 = c.get("price_change_percentage_24h", 0.0) or 0.0
            msg = (
                f"🚨 <b>5m Volume Spike</b>\n"
                f"• Coin: <b>{c.get('name','')} ({base})</b>\n"
                f"• Pair: <b>{pair}</b>\n"
                f"• Price: ${price:.8f}\n"
                f"• 24h: {chg24:.2f}%\n"
                f"• Spike: <b>{ratio:.1f}×</b> normal\n"
                f"• Time: {now}"
            )
            tg_send(msg)
            alerts += 1

    print(f"== Scan done: scanned={scanned}, alerts={alerts} ==")
    return 0

if __name__ == "__main__":
    exit(main())

