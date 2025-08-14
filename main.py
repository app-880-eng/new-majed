# -*- coding: utf-8 -*-
# 2025.py — Web + Scheduler for EURUSD & XAUUSD signals (simple rules)
# تشغيل على Render عبر: uvicorn 2025:app --host 0.0.0.0 --port $PORT

import asyncio, os, sys, traceback
from datetime import datetime, timedelta
from collections import defaultdict

import requests
import pandas as pd
import numpy as np
import yfinance as yf
from fastapi import FastAPI

# ---------------- إعدادات تيليجرام (ضع قيمك) ----------------
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "PUT_YOUR_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

# ---------------- إعدادات الاستراتيجية ----------------
# نستخدم رموز yfinance لهذين الزوجين فقط
YF_TICKERS = {
    "EURUSD":  "EURUSD=X",   # يورو/دولار
    "XAUUSD":  "XAUUSD=X",   # الذهب/دولار (سبوت)
}
SYMBOLS = ["EURUSD", "XAUUSD"]

TIMEFRAME = "15m"        # إطار 15 دقيقة
PERIOD    = "7d"         # يكفي لـ 15m
CHECK_EVERY_MIN = int(os.getenv("CHECK_EVERY_MIN", "10"))   # كل 10 دقايق
COOLDOWN_MIN    = int(os.getenv("COOLDOWN_MIN", "180"))     # تبريد 3 ساعات

# أهداف/وقف افتراضي لإضافتها بالنص (اختياري)
DEFAULTS = {
    "EURUSD": {"tp_pct": 0.004, "sl_pips": 30},   # 0.4% و 30 نقطة
    "XAUUSD": {"tp_usd": 10.0,  "sl_usd": 7.0},   # هدف 10$ ووقف 7$
}

# ---------------- أدوات مساعدة ----------------
def log(msg: str):
    print(f"[{datetime.utcnow().isoformat()}] {msg}", flush=True)

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or "PUT_" in TELEGRAM_TOKEN:
        log("⚠️ TELEGRAM_TOKEN غير مضبوط — لن يتم الإرسال.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            log(f"Telegram error {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Telegram exception: {e}")

def fetch_ohlc(symbol: str, timeframe: str = TIMEFRAME, period: str = PERIOD) -> pd.DataFrame:
    """
    يجلب بيانات الشموع من yfinance ويعيد DataFrame بأعمدة open/high/low/close
    """
    yf_ticker = YF_TICKERS[symbol]
    df = yf.Ticker(yf_ticker).history(period=period, interval=timeframe)
    if df is None or df.empty:
        raise RuntimeError(f"لا توجد بيانات لـ {symbol} ({yf_ticker})")
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    df = df[["open", "high", "low", "close"]].dropna().reset_index(drop=True)
    return df

_last_signal_time = defaultdict(lambda: datetime.min)  # تبريد لكل رمز

def compute_signal(df: pd.DataFrame, symbol: str):
    """
    منطق بسيط: تقاطع EMA20/EMA50 أو RSI يعبر 50 + شرط تقلب بسيط
    يعيد "BUY" أو "SELL" أو None
    """
    # EMA
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    # RSI يدوي
    delta = df["close"].diff()
    up = delta.clip(lower=0).rolling(14).mean()
    down = -delta.clip(upper=0).rolling(14).mean()
    rs = up / (down.replace(0, 1e-9))
    df["rsi"] = 100 - (100 / (1 + rs))

    # تقلب بسيط
    df["rng"] = (df["high"] - df["low"]).rolling(14).mean()
    vol_ok = (df["rng"].iloc[-1] / max(df["close"].iloc[-1], 1e-9)) > 0.001  # >= 0.10%

    ema_bull_cross = (df["ema20"].iloc[-2] <= df["ema50"].iloc[-2]) and (df["ema20"].iloc[-1] > df["ema50"].iloc[-1])
    ema_bear_cross = (df["ema20"].iloc[-2] >= df["ema50"].iloc[-2]) and (df["ema20"].iloc[-1] < df["ema50"].iloc[-1])
    rsi_up_50      = (df["rsi"].iloc[-2] < 50) and (df["rsi"].iloc[-1] >= 50)
    rsi_down_45    = (df["rsi"].iloc[-2] > 50) and (df["rsi"].iloc[-1] <= 45)

    price_above_ema = df["close"].iloc[-1] > df["ema20"].iloc[-1]

    buy  = vol_ok and price_above_ema and (ema_bull_cross or rsi_up_50)
    sell = vol_ok and (ema_bear_cross or rsi_down_45)

    # تبريد
    if (datetime.utcnow() - _last_signal_time[symbol]).total_seconds() < COOLDOWN_MIN * 60:
        return None

    if buy:
        _last_signal_time[symbol] = datetime.utcnow()
        return "BUY"
    if sell:
        _last_signal_time[symbol] = datetime.utcnow()
        return "SELL"
    return None

def format_signal_msg(symbol: str, side: str, price: float) -> str:
    if symbol == "EURUSD":
        tp = f"TP ~{DEFAULTS['EURUSD']['tp_pct']*100:.1f}%"
        sl = f"SL {DEFAULTS['EURUSD']['sl_pips']} pips"
    else:  # XAUUSD
        tp = f"TP ~${DEFAULTS['XAUUSD']['tp_usd']:.0f}"
        sl = f"SL ${DEFAULTS['XAUUSD']['sl_usd']:.0f}"
    return (
        f"🔔 Signal — {symbol}\n"
        f"Action: {side}\n"
        f"Price: {price:.5f}\n"
        f"TF: {TIMEFRAME}\n"
        f"{tp} | {sl}"
    )

# ---------------- تطبيق FastAPI + مجدول الخلفية ----------------
app = FastAPI(title="Signals EURUSD & XAUUSD")

@app.get("/")
def health():
    # فحص بسيط
    return {
        "status": "ok",
        "symbols": SYMBOLS,
        "check_every_min": CHECK_EVERY_MIN,
        "cooldown_min": COOLDOWN_MIN,
        "utc": datetime.utcnow().isoformat()
    }

async def scheduler_loop():
    log("🚀 Scheduler started.")
    while True:
        try:
            for symbol in SYMBOLS:
                try:
                    df = fetch_ohlc(symbol, TIMEFRAME, PERIOD)
                    if df is None or df.empty or len(df) < 60:
                        log(f"بيانات غير كافية لـ {symbol}")
                        continue
                    side = compute_signal(df, symbol)
                    if side:
                        price = float(df["close"].iloc[-1])
                        msg = format_signal_msg(symbol, side, price)
                        send_telegram(msg)
                        log(f"Sent: {symbol} {side} @ {price}")
                except Exception as e:
                    log(f"خطأ في {symbol}: {e}")
                    traceback.print_exc()
        except Exception as e:
            log(f"Loop error: {e}")
            traceback.print_exc()

        await asyncio.sleep(CHECK_EVERY_MIN * 60)

@app.on_event("startup")
async def _on_start():
    asyncio.create_task(scheduler_loop())

# يسمح بالتشغيل المحلي: python 2025.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("2025:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)