import requests, time, os
from datetime import datetime

# Get credentials from environment
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
VOLUME_MULTIPLIER = 2.0

def get_top500():
    coins = []
    for page in (1, 2):
        try:
            r = requests.get("https://api.coingecko.com/api/v3/coins/markets", params={
                "vs_currency":"usd", "order":"market_cap_desc",
                "per_page":250, "page":page, "sparkline":"false"
            }, timeout=20)
            r.raise_for_status()
            coins.extend(r.json())
            time.sleep(0.5)
        except: continue
    return coins

def get_binance_usdt_symbols():
    try:
        r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=20)
        r.raise_for_status()
        data = r.json()
        return {s["symbol"] for s in data.get("symbols", []) 
                if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"}
    except: return set()

def get_5m_klines(symbol):
    try:
        r = requests.get("https://api.binance.com/api/v3/klines", params={
            "symbol":symbol, "interval":"5m", "limit":31
        }, timeout=15)
        return r.json() if r.status_code==200 else []
    except: return []

def sma(vals): 
    return sum(vals)/len(vals) if vals else 0.0

def send_alert(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                     json={"chat_id":TELEGRAM_CHAT_ID, "text":text, "parse_mode":"HTML"}, 
                     timeout=15)
        return True
    except: return False

def main():
    print(f"🤖 Volume Scanner started at {datetime.utcnow()}")
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Missing bot token or chat ID")
        return
    
    # Get data
    coins = get_top500()
    usdt_pairs = get_binance_usdt_symbols()
    
    if not coins or not usdt_pairs:
        print("❌ Failed to get coin data")
        return
    
    print(f"📊 Scanning {len(coins)} coins across {len(usdt_pairs)} USDT pairs")
    
    alerts_sent = 0
    scanned_count = 0
    
    for coin in coins:
        base = (coin.get("symbol") or "").upper()
        if base in ("USDT","USDC","BUSD","DAI","FRAX"): continue
        
        pair = f"{base}USDT"
        if pair not in usdt_pairs: continue
        
        klines = get_5m_klines(pair)
        if not isinstance(klines, list) or len(klines) < 31: continue
        
        scanned_count += 1
        
        # Check volume spike
        volumes = [float(k[5]) for k in klines]
        avg30 = sma(volumes[-31:-1])
        current = volumes[-1]
        
        if avg30 > 0 and current > VOLUME_MULTIPLIER * avg30:
            ratio = current / avg30
            price = coin.get("current_price", 0)
            change24h = coin.get("price_change_percentage_24h", 0) or 0
            
            alert = f"""🚨 <b>VOLUME SPIKE ALERT</b>

💰 <b>{coin.get('name', 'Unknown')} ({base})</b>
💵 Price: ${price:.8f}
📈 24h: {change24h:.2f}%
📊 <b>{ratio:.1f}x</b> volume spike
🔥 Current: {current:,.0f}
📊 Average: {avg30:,.0f}
⏰ {datetime.utcnow().strftime('%H:%M UTC')}

🎯 5-min volume is {ratio:.1f}x higher than 30-bar average!"""
            
            if send_alert(alert):
                print(f"🚨 ALERT: {pair} - {ratio:.1f}x volume spike")
                alerts_sent += 1
            
        time.sleep(0.08)  # Rate limiting
    
    print(f"✅ Scan complete: {scanned_count} pairs scanned, {alerts_sent} alerts sent")
    
    # Summary alert every hour (when minute is 0)
    if datetime.utcnow().minute == 0:
        send_alert(f"📊 Hourly Update: Scanner active, monitoring {scanned_count} pairs from top 500 coins")

if __name__ == "__main__":
    main()
