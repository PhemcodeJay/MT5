# server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import json
import os
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LATEST_FILE = "latest_signals.json"

@app.get("/candles")
async def get_candles(symbol: str = "XAUUSDT", interval: str = "5"):
    # You can reuse your get_candles function from bot.py
    # This is a simplified proxy example
    try:
        import requests
        url = "https://api.bybit.com/v5/market/kline"
        params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": 200}
        r = requests.get(url, params=params)
        data = r.json()['result']['list']
        candles = [{
            "time": int(k[0]) // 1000,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4])
        } for k in reversed(data)]
        return {"candles": candles}
    except:
        return {"candles": []}

@app.get("/latest_signals")
async def latest_signals():
    if os.path.exists(LATEST_FILE):
        with open(LATEST_FILE) as f:
            return json.load(f)
    return []

@app.post("/trigger_scan")
async def trigger_scan():
    # Run your bot analysis in background
    subprocess.Popen(["python", "bot.py"])  # or better: call analyze() directly
    return {"status": "scan started"}