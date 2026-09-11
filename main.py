import os
import time
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- TELEGRAM CONFIGURATION (2 CHATS) ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
            requests.post(url, data=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Delivery Error for {chat_id}: {e}")

# --- MARKET HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram(f"🏖️ *MARKET HOLIDAY TODAY!*\nReason: {reason}\nScanner will not run today.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

# --- INTRADAY TRADE ENGINE STATE ---
trade_state = {
    "in_trade": False,
    "type": None,
    "entry": 0.0,
    "sl": 0.0,
    "t1": 0.0,
    "t2": 0.0,
    "t3": 0.0,
    "t1_hit": False,
    "t2_hit": False,
    "t3_hit": False
}

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
last_heartbeat_hour = -1

# --- INDICATORS FORMULA (PANDAS DIRECT - NO 'ta' MODULE CRASH) ---
def compute_indicators(df):
    close = df['Close']
    high = df['High']
    low = df['Low']
    volume = df['Volume'] if 'Volume' in df else pd.Series(0, index=df.index)

    # 9 & 21 Exponential Moving Averages
    df['EMA_9'] = close.ewm(span=9, adjust=False).mean()
    df['EMA_21'] = close.ewm(span=21, adjust=False).mean()

    # 14 Relative Strength Index (RSI)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 14 Average True Range (ATR)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()

    # VWAP Approximation
    typical_price = (high + low + close) / 3
    cum_vp = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    df['VWAP'] = np.where(cum_vol != 0, cum_vp / cum_vol, close)
    return df

send_telegram("🚀 *NIFTY 50 STRATEGY BOT ONLINE!*\n• Schedule: 09:00 AM - 03:40 PM IST\n• Strategy: EMA 9/21 Crossover + RSI + VWAP\n• Targets: T1, T2, T3 & Stop Loss Active\n• Dual Channel Dispatch Ready")

# --- MAIN RUNNING ENGINE ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%H:%M:%S')

        # 03:40 PM Clean Daily Exit
        if current_time >= datetime.strptime("15:40", "%H:%M").time():
            summary = (
                f"📊 *MARKET CLOSED (DAILY REPORT)*\n"
                f"Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Target Hits: {trade_stats['target_hits']}\n"
                f"• Stop Loss Hits: {trade_stats['sl_hits']}\n\n"
                f"Scanner shutting down cleanly. See you tomorrow at 09:00 AM IST!"
            )
            send_telegram(summary)
            break

        # 03:20 PM Intraday Auto-Exit
        if current_time >= datetime.strptime("15:20", "%H:%M").time() and trade_state["in_trade"]:
            send_telegram(f"⏰ *INTRADAY AUTO-EXIT ALERT (3:20 PM)*\n\nAsset: NIFTY 50\nMarket closing soon. Active position closed cleanly!")
            trade_state["in_trade"] = False

        # Live Scanning Data (5-minute candles)
        df = yf.download(tickers="^NSEI", period="5d", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if not df.empty and len(df) >= 30:
            df = compute_indicators(df)
            curr = df.iloc[-1]
            prev = df.iloc[-2]

            close = round(float(curr['Close']), 2)
            high = round(float(curr['High']), 2)
            low = round(float(curr['Low']), 2)
            atr = round(float(curr['ATR']), 2) if not np.isnan(curr['ATR']) else 25.0
            vwap = float(curr['VWAP']) if not np.isnan(curr['VWAP']) else close
            rsi = float(curr['RSI']) if not np.isnan(curr['RSI']) else 50.0

            ema9_curr, ema21_curr = float(curr['EMA_9']), float(curr['EMA_21'])
            ema9_prev, ema21_prev = float(prev['EMA_9']), float(prev['EMA_21'])

            # Target & SL Tracker
            if trade_state["in_trade"]:
                if trade_state["type"] == "BUY":
                    if low <= trade_state["sl"]:
                        trade_stats["sl_hits"] += 1
                        send_telegram(f"❌ *STOP LOSS HIT (BUY EXIT)*\n\nAsset: NIFTY 50\nExit Price: {trade_state['sl']:.2f}")
                        trade_state["in_trade"] = False

                    elif high >= trade_state["t1"] and not trade_state["t1_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯 *TARGET 1 ACHIEVED!*\n\nAsset: NIFTY 50\nT1 Price: {trade_state['t1']:.2f}\nBook partial profit!")
                        trade_state["t1_hit"] = True

                    elif high >= trade_state["t2"] and not trade_state["t2_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯🎯 *TARGET 2 ACHIEVED!*\n\nAsset: NIFTY 50\nT2 Price: {trade_state['t2']:.2f}\nMove SL to Entry!")
                        trade_state["t2_hit"] = True

                    elif high >= trade_state["t3"] and not trade_state["t3_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\nAsset: NIFTY 50\nT3 Price: {trade_state['t3']:.2f}\nBook full profits and exit!")
                        trade_state["in_trade"] = False

                elif trade_state["type"] == "SELL":
                    if high >= trade_state["sl"]:
                        trade_stats["sl_hits"] += 1
                        send_telegram(f"❌ *STOP LOSS HIT (SELL EXIT)*\n\nAsset: NIFTY 50\nExit Price: {trade_state['sl']:.2f}")
                        trade_state["in_trade"] = False

                    elif low <= trade_state["t1"] and not trade_state["t1_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯 *TARGET 1 ACHIEVED!*\n\nAsset: NIFTY 50\nT1 Price: {trade_state['t1']:.2f}\nBook partial profit!")
                        trade_state["t1_hit"] = True

                    elif low <= trade_state["t2"] and not trade_state["t2_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯🎯 *TARGET 2 ACHIEVED!*\n\nAsset: NIFTY 50\nT2 Price: {trade_state['t2']:.2f}\nMove SL to Entry!")
                        trade_state["t2_hit"] = True

                    elif low <= trade_state["t3"] and not trade_state["t3_hit"]:
                        trade_stats["target_hits"] += 1
                        send_telegram(f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\nAsset: NIFTY 50\nT3 Price: {trade_state['t3']:.2f}\nBook full profits and exit!")
                        trade_state["in_trade"] = False

            # Trade Entry Detector (09:30 AM - 03:20 PM)
            trade_window = datetime.strptime("09:30", "%H:%M").time() <= current_time < datetime.strptime("15:20", "%H:%M").time()
            if trade_window and not trade_state["in_trade"]:
                risk = max(round(atr * 1.5, 2), 20.0)

                # BUY Entry
                if (ema9_prev <= ema21_prev and ema9_curr > ema21_curr) and (close >= vwap) and (rsi > 50):
                    sl = round(close - risk, 2)
                    t1 = round(close + (risk * 1.0), 2)
                    t2 = round(close + (risk * 1.5), 2)
                    t3 = round(close + (risk * 2.0), 2)

                    trade_state.update({
                        "in_trade": True, "type": "BUY", "entry": close, "sl": sl,
                        "t1": t1, "t2": t2, "t3": t3, "t1_hit": False, "t2_hit": False, "t3_hit": False
                    })
                    trade_stats["total_signals"] += 1

                    msg = (
                        f"🟢 *NIFTY 50 BUY SIGNAL*\n\n"
                        f"⏰ Time: {current_time_str} IST\n"
                        f"💵 *Entry:* {close:.2f}\n"
                        f"🛑 *Stop Loss:* {sl:.2f}\n\n"
                        f"🎯 *Target 1:* {t1:.2f}\n"
                        f"🎯 *Target 2:* {t2:.2f}\n"
                        f"🎯 *Target 3:* {t3:.2f}"
                    )
                    send_telegram(msg)

                # SELL Entry
                elif (ema9_prev >= ema21_prev and ema9_curr < ema21_curr) and (close <= vwap) and (rsi < 50):
                    sl = round(close + risk, 2)
                    t1 = round(close - (risk * 1.0), 2)
                    t2 = round(close - (risk * 1.5), 2)
                    t3 = round(close - (risk * 2.0), 2)

                    trade_state.update({
                        "in_trade": True, "type": "SELL", "entry": close, "sl": sl,
                        "t1": t1, "t2": t2, "t3": t3, "t1_hit": False, "t2_hit": False, "t3_hit": False
                    })
                    trade_stats["total_signals"] += 1

                    msg = (
                        f"🔴 *NIFTY 50 SELL SIGNAL*\n\n"
                        f"⏰ Time: {current_time_str} IST\n"
                        f"💵 *Entry:* {close:.2f}\n"
                        f"🛑 *Stop Loss:* {sl:.2f}\n\n"
                        f"🎯 *Target 1:* {t1:.2f}\n"
                        f"🎯 *Target 2:* {t2:.2f}\n"
                        f"🎯 *Target 3:* {t3:.2f}"
                    )
                    send_telegram(msg)

        # 1-Hour Heartbeat Status with Nifty & BankNifty (+/- points & %)
        if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
            last_heartbeat_hour = now.hour
            try:
                indices_data = capital_market.market_watch_all_indices()
                hb_msg = f"💓 *HOURLY STATUS ALERT*\n⏰ Time: {current_time_str} IST\n\n"
                for target_idx in ["NIFTY 50", "NIFTY BANK"]:
                    idx_row = indices_data[indices_data['index'] == target_idx]
                    if not idx_row.empty:
                        last_p = float(str(idx_row['last'].values[0]).replace(',', ''))
                        prev_p = float(str(idx_row['previousClose'].values[0]).replace(',', ''))
                        diff = last_p - prev_p
                        pct = (diff / prev_p) * 100
                        hb_msg += f"• *{target_idx}:* {last_p:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram(hb_msg)
            except Exception as hb_err:
                print(f"Heartbeat Fetch Error: {hb_err}")

        time.sleep(30)

    except Exception as loop_error:
        print(f"Error in execution loop: {loop_error}")
        time.sleep(15)
