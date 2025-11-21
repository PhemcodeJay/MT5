# === XAUUSD MULTI-TIMEFRAME SCANNER (4H/1H Trend + 15M/5M Entry) ===
from flask import Flask, jsonify
import threading
from datetime import datetime, timedelta, timezone
import requests
from time import sleep

app = Flask(__name__)
latest_signal = None
latest_candles = []

def run_web():
    app.run(port=8000, debug=False, use_reloader=False)

@app.route('/candles')
def get_candles(): return jsonify({"candles": latest_candles[-200:]})

@app.route('/latest_signal')
def get_signal(): return jsonify(latest_signal or {})

@app.route('/trigger', methods=['POST'])
def trigger():
    global latest_signal, latest_candles
    print(f"Manual trigger @ {datetime.now(tz_utc3)}")
    signal = analyze()
    if signal:
        latest_signal = signal
        latest_candles = get_candles_tv("5", 200)
        print(f"SIGNAL: {signal['Side']} {signal['Type']} | Score: {signal['Score']}%")
    return "OK", 200

threading.Thread(target=run_web, daemon=True).start()

# === CONFIG ===
SYMBOL_TV = "OANDA:XAUUSD"
tz_utc3 = timezone(timedelta(hours=3))

INTERVAL_TREND_1 = "240"   # 4H
INTERVAL_TREND_2 = "60"    # 1H
INTERVAL_CONFIRM = "15"    # 15M
INTERVAL_ENTRY   = "5"     # 5M

RISK_PCT = 0.015
LEVERAGE = 20
LOT_SIZE = 0.01
MARGIN_USDT = 5

# === RELIABLE DATA FETCHER (Yahoo Finance + TradingView feed) ===
def get_candles_tv(interval: str, limit=500):
    symbol = "XAUUSD=X"
    range_map = {
        "1": "1d", "3": "1d", "5": "5d", "15": "5d",
        "60": "30d", "240": "60d", "D": "2y"
    }
    rng = range_map.get(interval, "5d")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": f"{interval}m" if interval.isdigit() else interval, "range": rng}
    
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()['chart']['result'][0]
        ts = data['timestamp']
        q = data['indicators']['quote'][0]
        
        bars = []
        for i in range(len(ts)):
            if None in (q['open'][i], q['close'][i]): continue
            bars.append({
                'time': ts[i],
                'open': q['open'][i],
                'high': q['high'][i],
                'low': q['low'][i],
                'close': q['close'][i],
                'volume': q['volume'][i] or 0
            })
        return bars[-limit:]
    except Exception as e:
        print(f"Data error {interval}m: {e}")
        return []

# === INDICATORS ===
def ema(values, period):
    if len(values) < period: return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return round(ema_val, 5)

def rsi(values, period=14):
    if len(values) < period + 1: return 50
    gains = losses = 0
    for i in range(1, period + 1):
        diff = values[-i] - values[-i-1]
        if diff > 0: gains += diff
        elif diff < 0: losses -= diff
    if losses == 0: return 100
    rs = gains / losses
    return round(100 - (100 / (1 + rs)), 2)

# === TREND DETECTION (4H + 1H) ===
def get_trend_direction():
    # 4H Trend
    c4 = get_candles_tv(INTERVAL_TREND_1, 100)
    if len(c4) < 50: return None
    close4 = [x['close'] for x in c4]
    ema55_4h = ema(close4, 55)
    ema200_4h = ema(close4, 200)
    price4 = close4[-1]

    # 1H Confirmation
    c1 = get_candles_tv(INTERVAL_TREND_2, 100)
    if len(c1) < 50: return None
    close1 = [x['close'] for x in c1]
    ema55_1h = ema(close1, 55)
    price1 = close1[-1]

    bullish_trend = (
        price4 > ema55_4h > ema200_4h and
        price1 > ema55_1h
    )
    bearish_trend = (
        price4 < ema55_4h < ema200_4h and
        price1 < ema55_1h
    )

    if bullish_trend: return "BULLISH"
    if bearish_trend: return "BEARISH"
    return "SIDEWAYS"

# === ENTRY CONDITIONS (15M + 5M) ===
def check_entry_setup(side: str):
    # 15M: Pullback to EMA21 + RSI divergence
    c15 = get_candles_tv(INTERVAL_CONFIRM, 100)
    if len(c15) < 40: return False, 0
    close15 = [x['close'] for x in c15]
    ema21_15m = ema(close15, 21)
    rsi15 = rsi(close15[-30:])

    # 5M: Momentum confirmation
    c5 = get_candles_tv(INTERVAL_ENTRY, 100)
    if len(c5) < 30: return False, 0
    close5 = [x['close'] for x in c5]
    price = close5[-1]
    ema9_5m = ema(close5, 9)
    ema21_5m = ema(close5, 21)
    rsi5 = rsi(close5)

    score = 0

    if side == "Buy":
        pullback_ok = close15[-2] <= ema21_15m * 1.002 and close15[-1] > ema21_15m
        momentum_ok = close5[-1] > ema9_5m > ema21_5m
        rsi_ok = 35 < rsi5 < 65 and rsi15 < 50
        if pullback_ok: score += 40
        if momentum_ok: score += 35
        if rsi_ok: score += 25
    else:  # Sell
        pullback_ok = close15[-2] >= ema21_15m * 0.998 and close15[-1] < ema21_15m
        momentum_ok = close5[-1] < ema9_5m < ema21_5m
        rsi_ok = 35 < rsi5 < 65 and rsi15 > 50
        if pullback_ok: score += 40
        if momentum_ok: score += 35
        if rsi_ok: score += 25

    return (score >= 80), score, price

# === MAIN ANALYZER ===
def analyze():
    trend = get_trend_direction()
    if trend == "SIDEWAYS":
        return None

    side = "Buy" if trend == "BULLISH" else "Sell"
    valid, score, price = check_entry_setup(side)
    if not valid:
        return None

    entry = round(price, 3)
    tp = round(entry * (1 + 0.018 if side == "Buy" else 1 - 0.018), 3)
    sl = round(entry * (1 - 0.015 if side == "Buy" else 1 + 0.015), 3)
    liq = round(entry * (1 - 1/LEVERAGE if side == "Buy" else 1 + 1/LEVERAGE), 3)

    type_map = {"BULLISH": "Trend Up", "BEARISH": "Trend Down"}
    
    signal = {
        'Symbol': 'XAUUSD',
        'Side': side,
        'Type': type_map[trend],
        'Score': min(99, score),
        'Entry': entry,
        'TP': tp,
        'SL': sl,
        'Trail': entry,
        'Market': entry,
        'BB Slope': 'N/A',
        'Qty': LOT_SIZE,
        'Margin': MARGIN_USDT,
        'Liq': liq,
        'Time': datetime.now(tz_utc3).strftime("%Y-%m-%d %H:%M:%S UTC+3"),
        'Trend': trend,
        'Confluence': '4H→1H→15M→5M'
    }
    return signal

# === FORMATTING ===
def format_signal(s):
    arrow = "UP" if s['Side'] == "Buy" else "DOWN"
    return f"""
╔════════════════ XAUUSD {arrow} SIGNAL ════════════════╗
║  {s['Type']:11} │ {s['Side']:4} │ Score: {s['Score']:2}%  ← 4H/1H/15M/5M    
║                                                    ║
║  Entry : {s['Entry']:<10}   TP  : {s['TP']:<10}      
║  SL    : {s['SL']:<10}   Liq : {s['Liq']}         
║                                                    ║
║  Time  : {s['Time']}          ║
╚═══════════════════════════════════════════════════╝
"""

# === MAIN LOOP ===
def main():
    print("XAUUSD Multi-Timeframe Scanner (4H→1H Trend + 15M→5M Entry) → LIVE")
    while True:
        now = datetime.now(tz_utc3).strftime("%H:%M")
        print(f"\nScanning {now} UTC+3 | Trend: {get_trend_direction() or 'Loading...'}")

        signal = analyze()
        if signal and signal['Score'] >= 80:
            print("\n" + format_signal(signal))
            # Optional: save PDF, send Telegram, etc.
        else:
            print("   No qualified setup")

        for i in range(300, 0, -1):
            m, s = divmod(i, 60)
            print(f"\rNext scan in {m:02d}:{s:02d}", end="")
            sleep(1)

if __name__ == "__main__":
    main()