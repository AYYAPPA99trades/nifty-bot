import os
import sys
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import requests
import numpy as np
import pandas as pd
import yfinance as yf

# ----------------- DIRECT CONFIGURATION -----------------
# 1. Telegram Bot 1 (New Bot - Channel & Admin)
BOT_1_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_1", "8804327561:AAHYL_srWzPSWCZR5aJe_tM0fD24HblsL_Q")
BOT_1_ADMIN_ID = os.getenv("TELEGRAM_CHAT_ID_1", "6789591588")
BOT_1_CHANNEL_ID = "-1004416495917"

# 2. Telegram Bot 2 (Ayyappa Backup Bot)
BOT_2_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_2", "8941192045:AAELQ21ZiFKnHMMySyOoMue-hzMgS9ZjotQ")
BOT_2_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID_2", "8996427731")

# 3. Gmail Configuration
SENDER_EMAIL = os.getenv("EMAIL_USER", "shinosanthagopi@gmail.com")
APP_PASSWORD = os.getenv("EMAIL_PASS", "trrt xigi xsqh czjf").replace(" ", "")
RECEIVER_EMAIL = os.getenv("EMAIL_RECEIVER", "shinosanthagopi@gmail.com")

STATE_FILE = "trade_state_pro.json"
IST = pytz.timezone("Asia/Kolkata")

# ----------------- BROADCAST FUNCTION -----------------

def send_telegram(text: str):
    """Ellam Telegram Chats-lum Channels-lum alert ayakunnu"""
    # Bot 1 -> Admin & Channel
    if BOT_1_TOKEN:
        url1 = f"https://api.telegram.org/bot{BOT_1_TOKEN}/sendMessage"
        for target_id in [BOT_1_ADMIN_ID, BOT_1_CHANNEL_ID]:
            if target_id:
                try:
                    requests.post(url1, json={"chat_id": target_id, "text": text, "parse_mode": "HTML"}, timeout=12)
                except Exception as e:
                    print(f"Error Bot 1 ({target_id}): {e}")

    # Bot 2 -> Chat ID
    if BOT_2_TOKEN and BOT_2_CHAT_ID:
        url2 = f"https://api.telegram.org/bot{BOT_2_TOKEN}/sendMessage"
        try:
            requests.post(url2, json={"chat_id": BOT_2_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=12)
        except Exception as e:
            print(f"Error Bot 2: {e}")

def send_email(subject: str, html_body: str):
    """Daily summary email ayakkunnu"""
    if not SENDER_EMAIL or not APP_PASSWORD:
        return
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(html_body, 'html'))
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Email Sent Successfully!")
    except Exception as e:
        print(f"Email Error: {e}")

# ----------------- STATE & DATA -----------------

def load_state():
    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "signals_count": 0,
        "max_signals": 5,
        "active_trade": None,
        "completed_trades": [],
        "startup_alert_sent": False,
        "daily_report_sent": False
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                if state.get("date") == today_str:
                    return state
        except Exception:
            pass
    return default_state

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_market_data():
    ticker = "^NSEI"
    df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
    if isinstance(df_5m.columns, pd.MultiIndex):
        df_5m.columns = df_5m.columns.get_level_values(0)
    return df_5m

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df['High'] + df['Low'] + df['Close']) / 3.0
    vol = df['Volume'].replace(0, 1)
    return (tp * vol).cumsum() / vol.cumsum()

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 2.0):
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    hl2 = (df['High'] + df['Low']) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=df.index, dtype='float64')
    direction = pd.Series(index=df.index, dtype='int64')
    in_uptrend = True

    for i in range(period, len(df)):
        c = df['Close'].iloc[i]
        if c > upperband.iloc[i-1]:
            in_uptrend = True
        elif c < lowerband.iloc[i-1]:
            in_uptrend = False

        if in_uptrend:
            supertrend.iloc[i] = lowerband.iloc[i]
            direction.iloc[i] = 1
        else:
            supertrend.iloc[i] = upperband.iloc[i]
            direction.iloc[i] = -1

    return supertrend, direction

# ----------------- TRADE LOGIC -----------------

def manage_active_trade(df_5m, state):
    trade = state.get("active_trade")
    if not trade:
        return False

    curr_close = float(df_5m['Close'].iloc[-1])
    entry = trade["entry_price"]
    current_sl = trade["current_sl"]
    t1 = trade["t1"]
    t2 = trade["t2"]
    t3 = trade["t3"]
    strike = trade["strike"]
    trade_type = trade["type"]

    if trade_type == "BUY_CE":
        if curr_close >= t3:
            send_telegram(f"🎉 <b>TARGET 3 HIT! (NIFTY {strike} CE)</b>\nCMP: {curr_close:.2f}\nGain: +{curr_close - entry:.2f} pts")
            state["completed_trades"].append({"type": trade_type, "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True
        elif curr_close >= t1 and not trade.get("t1_hit"):
            trade["t1_hit"] = True
            trade["current_sl"] = entry
            send_telegram(f"🎯 <b>TARGET 1 HIT! (NIFTY {strike} CE)</b>\nCMP: {curr_close:.2f}\n🔒 SL Trailed to Cost ({entry:.2f})")
            save_state(state)
        elif curr_close <= current_sl:
            send_telegram(f"🛑 <b>SL HIT (NIFTY {strike} CE)</b>\nCMP: {curr_close:.2f}\nP&L: {curr_close - entry:+.2f} pts")
            state["completed_trades"].append({"type": trade_type, "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

    elif trade_type == "BUY_PE":
        if curr_close <= t3:
            send_telegram(f"🎉 <b>TARGET 3 HIT! (NIFTY {strike} PE)</b>\nCMP: {curr_close:.2f}\nGain: +{entry - curr_close:.2f} pts")
            state["completed_trades"].append({"type": trade_type, "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True
        elif curr_close <= t1 and not trade.get("t1_hit"):
            trade["t1_hit"] = True
            trade["current_sl"] = entry
            send_telegram(f"🎯 <b>TARGET 1 HIT! (NIFTY {strike} PE)</b>\nCMP: {curr_close:.2f}\n🔒 SL Trailed to Cost ({entry:.2f})")
            save_state(state)
        elif curr_close >= current_sl:
            send_telegram(f"🛑 <b>SL HIT (NIFTY {strike} PE)</b>\nCMP: {curr_close:.2f}\nP&L: {entry - curr_close:+.2f} pts")
            state["completed_trades"].append({"type": trade_type, "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

    save_state(state)
    return True

def scan_for_entries(df_5m, state):
    if state["signals_count"] >= state["max_signals"]:
        return

    curr = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    close = float(curr['Close'])
    vwap = float(curr['VWAP'])
    atr = float(curr['ATR'])
    st_dir = int(curr['ST_Dir'])

    sl_dist = round(max(20.0, atr * 1.2), 1)
    t1_dist = round(sl_dist * 1.0, 1)
    t2_dist = round(sl_dist * 2.0, 1)
    t3_dist = round(sl_dist * 3.0, 1)
    atm_strike = int(round(close / 50.0) * 50)

    bullish_trigger = (close > vwap) and (st_dir == 1) and (prev['Close'] <= prev['VWAP'] or close > prev['High'])
    bearish_trigger = (close < vwap) and (st_dir == -1) and (prev['Close'] >= prev['VWAP'] or close < prev['Low'])

    if bullish_trigger:
        state["signals_count"] += 1
        state["active_trade"] = {
            "type": "BUY_CE", "strike": atm_strike, "entry_price": close,
            "original_sl": close - sl_dist, "current_sl": close - sl_dist,
            "t1": close + t1_dist, "t2": close + t2_dist, "t3": close + t3_dist,
            "t1_hit": False, "t2_hit": False
        }
        msg = (
            f"🚀 <b>NEW PRO SIGNAL: NIFTY {atm_strike} CE</b> 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Spot CMP:</b> {close:.2f}\n"
            f"🛑 <b>Spot SL:</b> {close - sl_dist:.2f} (-{sl_dist} pts)\n"
            f"🎯 <b>Target 1:</b> {close + t1_dist:.2f} (+{t1_dist} pts)\n"
            f"🏆 <b>Target 2:</b> {close + t2_dist:.2f} (+{t2_dist} pts)\n"
            f"🎉 <b>Target 3:</b> {close + t3_dist:.2f} (+{t3_dist} pts)"
        )
        send_telegram(msg)
        save_state(state)

    elif bearish_trigger:
        state["signals_count"] += 1
        state["active_trade"] = {
            "type": "BUY_PE", "strike": atm_strike, "entry_price": close,
            "original_sl": close + sl_dist, "current_sl": close + sl_dist,
            "t1": close - t1_dist, "t2": close - t2_dist, "t3": close - t3_dist,
            "t1_hit": False, "t2_hit": False
        }
        msg = (
            f"🔻 <b>NEW PRO SIGNAL: NIFTY {atm_strike} PE</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Spot CMP:</b> {close:.2f}\n"
            f"🛑 <b>Spot SL:</b> {close + sl_dist:.2f} (+{sl_dist} pts)\n"
            f"🎯 <b>Target 1:</b> {close - t1_dist:.2f} (-{t1_dist} pts)\n"
            f"🏆 <b>Target 2:</b> {close - t2_dist:.2f} (-{t2_dist} pts)\n"
            f"🎉 <b>Target 3:</b> {close - t3_dist:.2f} (-{t3_dist} pts)"
        )
        send_telegram(msg)
        save_state(state)

def main():
    state = load_state()
    now_ist = datetime.datetime.now(IST)

    # Startup Alert (First Run)
    if not state.get("startup_alert_sent"):
        startup_msg = (
            f"🟢 <b>NIFTY PRO BOT STARTED!</b>\n"
            f"⏰ <b>Time:</b> {now_ist.strftime('%H:%M:%S')} IST\n"
            f"📡 <b>Status:</b> All Channels, Chats & Email Connected!"
        )
        send_telegram(startup_msg)
        send_email("🟢 Nifty Bot Started", startup_msg.replace("\n", "<br>"))
        state["startup_alert_sent"] = True
        save_state(state)

    df_5m = get_market_data()
    if df_5m.empty:
        return

    df_5m['VWAP'] = calculate_vwap(df_5m)
    df_5m['ATR'] = calculate_atr(df_5m, 14)
    df_5m['Supertrend'], df_5m['ST_Dir'] = calculate_supertrend(df_5m, 10, 2.0)

    has_active = manage_active_trade(df_5m, state)
    if not has_active:
        scan_for_entries(df_5m, state)

if __name__ == "__main__":
    main()
