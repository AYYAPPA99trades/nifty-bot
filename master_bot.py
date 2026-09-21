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
BOT_1_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_1", "8941192045:AAELQ21ZiFKnHMMysyOoMue-hzMgS9ZjotQ")
BOT_1_ADMIN_ID = os.getenv("TELEGRAM_CHAT_ID_1", "6789591588")
BOT_1_CHANNEL_ID = "-1004416495917"

# 2. Telegram Bot 2 (Ayyappa Backup Bot)
BOT_2_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_2", "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0")
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
    if BOT_1_TOKEN:
        url1 = f"https://api.telegram.org/bot{BOT_1_TOKEN}/sendMessage"
        for target_id in [BOT_1_ADMIN_ID, BOT_1_CHANNEL_ID]:
            if target_id:
                try:
                    requests.post(url1, json={"chat_id": target_id, "text": text, "parse_mode": "HTML"}, timeout=12)
                except Exception as e:
                    print(f"Error Bot 1 ({target_id}): {e}")

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
        "premarket_sent": False,
        "daily_report_sent": False,
        "expiry_report_sent": False
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
    df_daily = yf.download(ticker, period="1mo", interval="1d", progress=False)
    df_1h = yf.download(ticker, period="1mo", interval="1h", progress=False)

    for d in [df_5m, df_daily, df_1h]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    return df_5m, df_daily, df_1h

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

def calculate_cpr_and_pivots(df_daily: pd.DataFrame):
    prev = df_daily.iloc[-2] if len(df_daily) >= 2 else df_daily.iloc[-1]
    h = float(prev['High'])
    l = float(prev['Low'])
    c = float(prev['Close'])

    pivot = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = (pivot - bc) + pivot
    top_cpr = max(tc, bc)
    bottom_cpr = min(tc, bc)
    cpr_width = abs(top_cpr - bottom_cpr)
    cpr_pct = (cpr_width / c) * 100

    r1 = (2 * pivot) - l
    s1 = (2 * pivot) - h

    if cpr_pct < 0.15:
        bias = "🔥 Narrow CPR (High Trending Potential)"
    elif cpr_pct > 0.40:
        bias = "⚠️ Wide CPR (Range-bound Expected)"
    else:
        bias = "⚖️ Normal CPR"

    return pivot, top_cpr, bottom_cpr, h, l, r1, s1, bias

# ----------------- PRE-MARKET & SUMMARY ALERTS -----------------

def check_premarket_and_reports(df_daily, state):
    now = datetime.datetime.now(IST)
    cur_time = now.time()

    # 1. Pre-Market Structure Alert (around 9:00 - 9:15 AM)
    if datetime.time(9, 0) <= cur_time <= datetime.time(9, 20) and not state.get("premarket_sent"):
        pivot, tc, bc, pdh, pdl, r1, s1, bias = calculate_cpr_and_pivots(df_daily)
        msg = (
            f"🌅 <b>NIFTY 50 PRE-MARKET STRUCTURE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>CPR Bias:</b> {bias}\n"
            f"• Top CPR: <b>{tc:.1f}</b> | Central: <b>{pivot:.1f}</b> | Bottom: <b>{bc:.1f}</b>\n"
            f"• PDH: <b>{pdh:.1f}</b> | PDL: <b>{pdl:.1f}</b>\n"
            f"• R1: <b>{r1:.1f}</b> | S1: <b>{s1:.1f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: Narrow CPR Breakout + 15M ORB Watch</i>"
        )
        send_telegram(msg)
        state["premarket_sent"] = True
        save_state(state)

    # 2. Daily Report (3:40 PM IST)
    if datetime.time(15, 38) <= cur_time <= datetime.time(15, 55) and not state.get("daily_report_sent"):
        trades = state.get("completed_trades", [])
        total_pts = sum([t.get("pts", 0.0) for t in trades])
        wins = len([t for t in trades if t.get("pts", 0.0) > 0])
        losses = len([t for t in trades if t.get("pts", 0.0) <= 0])

        report_msg = (
            f"📊 <b>NIFTY 50 DAILY PERFORMANCE REPORT</b>\n"
            f"📅 Date: {now.strftime('%Y-%m-%d')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Total Signals: <b>{len(trades)}</b>\n"
            f"✅ Profitable: <b>{wins}</b> | 🛑 SL/Exit: <b>{losses}</b>\n"
            f"💰 Net Points: <b>{total_pts:+.2f} pts</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>Session Closed for Today.</i>"
        )
        send_telegram(report_msg)
        send_email(f"Nifty Daily Report - {now.strftime('%Y-%m-%d')}", report_msg.replace("\n", "<br>"))
        state["daily_report_sent"] = True
        save_state(state)

    # 3. Dynamic Expiry Day Report (Handles holiday shifts to Tuesday/Wednesday/Thursday)
    weekday_name = now.strftime('%A')
    # Normal Nifty expiry is Thursday; if Friday is holiday, it shifts to Wednesday, etc.
    if weekday_name in ['Thursday', 'Wednesday', 'Tuesday'] and cur_time >= datetime.time(15, 30) and not state.get("expiry_report_sent"):
        trades = state.get("completed_trades", [])
        total_pts = sum([t.get("pts", 0.0) for t in trades])
        exp_msg = (
            f"🎯 <b>NIFTY EXPIRY SESSION SUMMARY</b>\n"
            f"📅 Expiry Date: {now.strftime('%Y-%m-%d')} ({weekday_name})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ Weekly Expiry Contracts Monitored.\n"
            f"💰 Net P&L Generated Today: <b>{total_pts:+.2f} pts</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram(exp_msg)
        state["expiry_report_sent"] = True
        save_state(state)

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
        elif curr_close >= t2 and not trade.get("t2_hit"):
            trade["t2_hit"] = True
            trade["current_sl"] = t1
            send_telegram(f"🏆 <b>TARGET 2 HIT! (NIFTY {strike} CE)</b>\nCMP: {curr_close:.2f}\n🔒 SL Trailed to Target 1 ({t1:.2f})")
            save_state(state)
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
        elif curr_close <= t2 and not trade.get("t2_hit"):
            trade["t2_hit"] = True
            trade["current_sl"] = t1
            send_telegram(f"🏆 <b>TARGET 2 HIT! (NIFTY {strike} PE)</b>\nCMP: {curr_close:.2f}\n🔒 SL Trailed to Target 1 ({t1:.2f})")
            save_state(state)
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

def scan_for_entries(df_5m, df_1h, top_cpr, bottom_cpr, state):
    if state.get("signals_count", 0) >= state.get("max_signals", 5):
        return

    curr = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    close = float(curr['Close'])
    vwap = float(curr['VWAP'])
    atr = float(curr['ATR'])
    st_dir = int(curr['ST_Dir'])

    # 1. Higher Timeframe Trend Filter (1-Hour EMA 50)
    ema50_1h = df_1h['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
    htf_bullish = close >= ema50_1h
    htf_bearish = close <= ema50_1h

    # 2. Volume Surge Filter
    vol_avg = df_5m['Volume'].rolling(10).mean().iloc[-1]
    has_volume = curr['Volume'] >= (vol_avg * 0.9) if vol_avg > 0 else True

    # 3. ORB Check (First 15-min)
    today_candles = df_5m.between_time("09:15", "15:30")
    if len(today_candles) >= 3:
        orb_high = float(today_candles.iloc[:3]['High'].max())
        orb_low = float(today_candles.iloc[:3]['Low'].min())
    else:
        orb_high = close
        orb_low = close

    sl_dist = round(max(20.0, atr * 1.2), 1)
    t1_dist = round(sl_dist * 1.0, 1)
    t2_dist = round(sl_dist * 2.0, 1)
    t3_dist = round(sl_dist * 3.0, 1)
    atm_strike = int(round(close / 50.0) * 50)

    # Bullish: HTF + Above VWAP + Above CPR + Supertrend + Volume + Pullback/ORB
    bullish_trigger = (
        htf_bullish and
        (close > vwap) and
        (close > top_cpr) and
        (st_dir == 1) and
        has_volume and
        (prev['Close'] <= prev['VWAP'] or close > orb_high or close > prev['High'])
    )

    # Bearish: HTF + Below VWAP + Below CPR + Supertrend + Volume + Breakdown/ORB
    bearish_trigger = (
        htf_bearish and
        (close < vwap) and
        (close < bottom_cpr) and
        (st_dir == -1) and
        has_volume and
        (prev['Close'] >= prev['VWAP'] or close < orb_low or close < prev['Low'])
    )

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
            f"🎉 <b>Target 3:</b> {close + t3_dist:.2f} (+{t3_dist} pts)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: CPR Break + VWAP + 1H Trend + Volume</i>"
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
            f"🎉 <b>Target 3:</b> {close - t3_dist:.2f} (-{t3_dist} pts)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: CPR Breakdown + VWAP + 1H Trend + Volume</i>"
        )
        send_telegram(msg)
        save_state(state)

def main():
    state = load_state()
    now_ist = datetime.datetime.now(IST)
    cur_time = now_ist.time()

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

    df_5m, df_daily, df_1h = get_market_data()
    if df_5m.empty or df_daily.empty or df_1h.empty:
        return

    # Check Pre-market levels & Closing reports
    check_premarket_and_reports(df_daily, state)

    df_5m['VWAP'] = calculate_vwap(df_5m)
    df_5m['ATR'] = calculate_atr(df_5m, 14)
    df_5m['Supertrend'], df_5m['ST_Dir'] = calculate_supertrend(df_5m, 10, 2.0)

    has_active = manage_active_trade(df_5m, state)
    
    # Active trade illengil entry scan cheyyuka (9:15 AM - 3:20 PM)
    if not has_active and datetime.time(9, 15) <= cur_time <= datetime.time(15, 20):
        pivot, top_cpr, bottom_cpr, _, _, _, _, _ = calculate_cpr_and_pivots(df_daily)
        scan_for_entries(df_5m, df_1h, top_cpr, bottom_cpr, state)

if __name__ == "__main__":
    main()
