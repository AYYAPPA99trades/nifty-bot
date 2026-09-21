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

# ----------------- MULTI-TELEGRAM CONFIGURATION -----------------
# 1. പുതിയ Bot & Channels/Admin
PRIMARY_BOT_TOKEN = os.getenv("PRIMARY_BOT_TOKEN", "8804327561:AAHYL_srWzPSWCZR5aJe_tM0fD24HblsL_Q")
ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "-1004416495917"
PUBLIC_ALERT_IDS = [CHANNEL_CHAT_ID, ADMIN_CHAT_ID]

# 2. ബാക്കപ്പ് / മുൻപ് നൽകിയ മറ്റ് ബോട്ടുകൾ
BACKUP_TARGETS = [
    {
        "name": "Ayyappan Alert Bot",
        "token": os.getenv("BACKUP_BOT_TOKEN", "8941192045:AAELQ21ZiFKnHMMySyOoMue-hzMgS9ZjotQ"),
        "chat_id": os.getenv("BACKUP_CHAT_ID", "8996427731")
    }
]

# Gmail SMTP Configuration
SENDER_EMAIL = os.getenv("EMAIL_USER", "shinosanthagopi@gmail.com")
APP_PASSWORD = os.getenv("EMAIL_PASS", "trrt xigi xsqh czjf").replace(" ", "")
RECEIVER_EMAIL = os.getenv("EMAIL_RECEIVER", "shinosanthagopi@gmail.com")

STATE_FILE = "trade_state_pro.json"
IST = pytz.timezone("Asia/Kolkata")

# ----------------- BROADCAST FUNCTION -----------------

def send_telegram(text: str):
    """എല്ലാ ടെലിഗ്രാം ചാനലുകളിലേക്കും അഡ്മിൻ ഐഡികളിലേക്കും ഒരേസമയം മെസ്സേജ് അയക്കുന്നു"""
    # 1. പുതിയ Bot വഴി Channel-ലേക്കും Admin-ലേക്കും അയക്കുന്നു
    if PRIMARY_BOT_TOKEN:
        url = f"https://api.telegram.org/bot{PRIMARY_BOT_TOKEN}/sendMessage"
        for target_id in PUBLIC_ALERT_IDS:
            payload = {"chat_id": target_id, "text": text, "parse_mode": "HTML"}
            try:
                res = requests.post(url, json=payload, timeout=12)
                if not res.ok:
                    print(f"Telegram Failed for {target_id}: {res.text}")
            except Exception as e:
                print(f"Error sending to {target_id}: {e}")

    # 2. ബാക്കപ്പ് ബോട്ടിലേക്ക് അയക്കുന്നു
    for target in BACKUP_TARGETS:
        token = target["token"]
        cid = target["chat_id"]
        if token and cid:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": cid, "text": text, "parse_mode": "HTML"}
            try:
                requests.post(url, json=payload, timeout=12)
            except Exception as e:
                print(f"Error sending to {target['name']}: {e}")

def send_email(subject: str, html_body: str):
    """Gmail വഴി ഡെയ്‌ലി പെർഫോമൻസ് റിപ്പോർട്ട് അയക്കുന്നു"""
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
        print("Email Alert Sent Successfully!")
    except Exception as e:
        print(f"Email Error: {e}")

# ----------------- STATE MANAGEMENT -----------------

def load_state():
    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "signals_count": 0,
        "max_signals": 5,
        "active_trade": None,
        "completed_trades": [],
        "startup_alert_sent": False,
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

# ----------------- TECHNICAL INDICATORS -----------------

def get_market_data():
    ticker = "^NSEI"
    df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
    df_daily = yf.download(ticker, period="1mo", interval="1d", progress=False)

    for d in [df_5m, df_daily]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    return df_5m, df_daily

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

# ----------------- LIVE TRADE MANAGEMENT -----------------

def manage_active_trade(df_5m, state):
    trade = state.get("active_trade")
    if not trade:
        return False

    curr_close = float(df_5m['Close'].iloc[-1])
    curr_vwap = float(df_5m['VWAP'].iloc[-1])
    st_dir = int(df_5m['ST_Dir'].iloc[-1])
    
    trade_type = trade["type"]
    entry = trade["entry_price"]
    current_sl = trade["current_sl"]
    t1 = trade["t1"]
    t2 = trade["t2"]
    t3 = trade["t3"]
    strike = trade["strike"]

    if trade_type == "BUY_CE":
        if curr_close >= t3:
            msg = (
                f"🎉 <b>FINAL TARGET 3 REACHED! (NIFTY {strike} CE)</b> 🚀\n\n"
                f"💵 Spot CMP: <b>{curr_close:.2f}</b>\n"
                f"💰 Total Gain: <b>+{curr_close - entry:.2f} pts</b>\n"
                f"✅ <b>Action:</b> പൂർണ്ണമായും ലാഭം എടുത്ത് എക്സിറ്റ് ചെയ്യുക!"
            )
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "T3_HIT", "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close >= t2 and not trade.get("t2_hit"):
            trade["t2_hit"] = True
            trade["current_sl"] = t1
            send_telegram(f"🏆 <b>TARGET 2 HIT! (NIFTY {strike} CE)</b>\n💵 CMP: {curr_close:.2f}\n🛡️ SL Trailed to T1 (<b>{t1:.2f}</b>)")
            save_state(state)

        elif curr_close >= t1 and not trade.get("t1_hit"):
            trade["t1_hit"] = True
            trade["current_sl"] = entry
            send_telegram(f"🎯 <b>TARGET 1 HIT! (NIFTY {strike} CE)</b>\n💵 CMP: {curr_close:.2f}\n🔒 SL Trailed to Entry Cost (<b>{entry:.2f}</b>) - RISK FREE!")
            save_state(state)

        elif st_dir == -1 or curr_close < curr_vwap:
            send_telegram(f"⚠️ <b>REVERSAL EXIT (NIFTY {strike} CE)</b>\nനിഫ്റ്റി VWAP-ന് താഴേക്ക് പോയി.\n💵 Spot CMP: {curr_close:.2f}\n🚪 Trade Closed.")
            state["completed_trades"].append({"type": trade_type, "result": "REVERSAL", "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close <= current_sl:
            alert_type = "COST-TO-COST EXIT" if trade.get("t1_hit") else "STOP LOSS HIT"
            send_telegram(f"🛑 <b>{alert_type}</b>\n📌 Symbol: NIFTY {strike} CE\n💵 Exit Price: {curr_close:.2f}\n📊 P&L: {curr_close - entry:+.2f} pts")
            state["completed_trades"].append({"type": trade_type, "result": "SL_HIT", "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

    elif trade_type == "BUY_PE":
        if curr_close <= t3:
            msg = (
                f"🎉 <b>FINAL TARGET 3 REACHED! (NIFTY {strike} PE)</b> 🚀\n\n"
                f"💵 Spot CMP: <b>{curr_close:.2f}</b>\n"
                f"💰 Total Gain: <b>+{entry - curr_close:.2f} pts</b>\n"
                f"✅ <b>Action:</b> പൂർണ്ണമായും ലാഭം എടുത്ത് എക്സിറ്റ് ചെയ്യുക!"
            )
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "T3_HIT", "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close <= t2 and not trade.get("t2_hit"):
            trade["t2_hit"] = True
            trade["current_sl"] = t1
            send_telegram(f"🏆 <b>TARGET 2 HIT! (NIFTY {strike} PE)</b>\n💵 CMP: {curr_close:.2f}\n🛡️ SL Trailed to T1 (<b>{t1:.2f}</b>)")
            save_state(state)

        elif curr_close <= t1 and not trade.get("t1_hit"):
            trade["t1_hit"] = True
            trade["current_sl"] = entry
            send_telegram(f"🎯 <b>TARGET 1 HIT! (NIFTY {strike} PE)</b>\n💵 CMP: {curr_close:.2f}\n🔒 SL Trailed to Entry Cost (<b>{entry:.2f}</b>) - RISK FREE!")
            save_state(state)

        elif st_dir == 1 or curr_close > curr_vwap:
            send_telegram(f"⚠️ <b>REVERSAL EXIT (NIFTY {strike} PE)</b>\nനിഫ്റ്റി VWAP-ന് മുകളിലേക്ക് പോയി.\n💵 Spot CMP: {curr_close:.2f}\n🚪 Trade Closed.")
            state["completed_trades"].append({"type": trade_type, "result": "REVERSAL", "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close >= current_sl:
            alert_type = "COST-TO-COST EXIT" if trade.get("t1_hit") else "STOP LOSS HIT"
            send_telegram(f"🛑 <b>{alert_type}</b>\n📌 Symbol: NIFTY {strike} PE\n💵 Exit Price: {curr_close:.2f}\n📊 P&L: {entry - curr_close:+.2f} pts")
            state["completed_trades"].append({"type": trade_type, "result": "SL_HIT", "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

    save_state(state)
    return True

# ----------------- ENTRY SCANNER -----------------

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
    
    today_candles = df_5m.between_time("09:15", "15:30")
    if len(today_candles) < 3:
        return
    orb_high = float(today_candles.iloc[:3]['High'].max())
    orb_low = float(today_candles.iloc[:3]['Low'].min())

    bullish_trigger = (close > vwap) and (st_dir == 1) and (close > orb_high or prev['Close'] <= prev['VWAP'])
    bearish_trigger = (close < vwap) and (st_dir == -1) and (close < orb_low or prev['Close'] >= prev['VWAP'])

    opt_sl_pts = round(sl_dist * 0.5, 1)

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
            f"🛑 <b>Spot SL:</b> {close - sl_dist:.2f} (-{sl_dist} pts) [Opt SL: -{opt_sl_pts} pts]\n"
            f"🎯 <b>Target 1:</b> {close + t1_dist:.2f} (+{t1_dist} pts) [Trail to Cost]\n"
            f"🏆 <b>Target 2:</b> {close + t2_dist:.2f} (+{t2_dist} pts)\n"
            f"🎉 <b>Target 3:</b> {close + t3_dist:.2f} (+{t3_dist} pts)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: Confluence ORB + VWAP + ATR Momentum</i>"
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
            f"🛑 <b>Spot SL:</b> {close + sl_dist:.2f} (+{sl_dist} pts) [Opt SL: -{opt_sl_pts} pts]\n"
            f"🎯 <b>Target 1:</b> {close - t1_dist:.2f} (-{t1_dist} pts) [Trail to Cost]\n"
            f"🏆 <b>Target 2:</b> {close - t2_dist:.2f} (-{t2_dist} pts)\n"
            f"🎉 <b>Target 3:</b> {close - t3_dist:.2f} (-{t3_dist} pts)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: Confluence ORB + VWAP Breakdown</i>"
        )
        send_telegram(msg)
        save_state(state)

# ----------------- REPORTS & NOTIFICATIONS -----------------

def check_reports_and_time(state, df_5m):
    now_ist = datetime.datetime.now(IST)
    current_time = now_ist.time()

    # 3:40 PM Daily Performance Report (Telegram & Email)
    if datetime.time(15, 40) <= current_time <= datetime.time(15, 55) and not state.get("daily_report_sent"):
        trades = state.get("completed_trades", [])
        total_pts = sum([t["pts"] for t in trades])
        wins = len([t for t in trades if t["pts"] > 0])
        losses = len([t for t in trades if t["pts"] <= 0])
        
        report_msg = (
            f"📊 <b>NIFTY 50 DAILY PERFORMANCE REPORT</b>\n"
            f"📅 Date: {now_ist.strftime('%d-%m-%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔢 Total Trades: <b>{len(trades)}</b>\n"
            f"✅ Wins: <b>{wins}</b> | ❌ Losses: <b>{losses}</b>\n"
            f"💰 Net P&L: <b>{total_pts:+.2f} pts</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <i>Trading Bot Session Closed for Today.</i>"
        )
        send_telegram(report_msg)
        send_email(f"📊 NIFTY 50 Daily Report - {now_ist.strftime('%d-%m-%Y')}", report_msg.replace("\n", "<br>"))
        state["daily_report_sent"] = True
        save_state(state)

    # Expiry Check
    if not state.get("expiry_report_sent") and current_time >= datetime.time(15, 30):
        is_expiry_day = (now_ist.strftime('%A') in ['Thursday', 'Tuesday'])
        if is_expiry_day:
            trades = state.get("completed_trades", [])
            total_pts = sum([t["pts"] for t in trades])
            expiry_msg = (
                f"🎯 <b>NIFTY EXPIRY SPECIAL CLOSING REPORT</b>\n"
                f"📅 Date: {now_ist.strftime('%d-%m-%Y')} ({now_ist.strftime('%A')})\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ Expiry Session Monitored Successfully.\n"
                f"💰 Total Net Gain: <b>{total_pts:+.2f} pts</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram(expiry_msg)
            send_email(f"🎯 Nifty Expiry Report - {now_ist.strftime('%d-%m-%Y')}", expiry_msg.replace("\n", "<br>"))
            state["expiry_report_sent"] = True
            save_state(state)

# ----------------- MAIN CONTROLLER -----------------

def main():
    state = load_state()
    now_ist = datetime.datetime.now(IST)
    current_time = now_ist.time()

    # 1. ബോട്ട് സ്റ്റാർട്ട് അലേർട്ട് (Channel & Admin-ലേക്ക് എത്തും)
    if not state.get("startup_alert_sent"):
        startup_msg = (
            f"🟢 <b>NIFTY PRO BOT STARTED!</b>\n"
            f"⏰ <b>Time:</b> {now_ist.strftime('%H:%M:%S')} IST\n"
            f"📅 <b>Date:</b> {now_ist.strftime('%d-%m-%Y')}\n"
            f"📡 <b>Status:</b> Broadcast Active (Channel & Admin Linked)\n"
            f"⏱ <b>Scan Window:</b> 09:00 AM - 03:40 PM"
        )
        send_telegram(startup_msg)
        state["startup_alert_sent"] = True
        save_state(state)

    df_5m, df_daily = get_market_data()
    if df_5m.empty or df_daily.empty:
        return

    df_5m['VWAP'] = calculate_vwap(df_5m)
    df_5m['ATR'] = calculate_atr(df_5m, 14)
    df_5m['Supertrend'], df_5m['ST_Dir'] = calculate_supertrend(df_5m, 10, 2.0)

    # 2. Manage Active Trades
    has_active = manage_active_trade(df_5m, state)

    # 3. Scan For Entries
    if not has_active and datetime.time(9, 0) <= current_time < datetime.time(15, 20):
        scan_for_entries(df_5m, state)

    # 4. Reports Check (3:40 PM)
    check_reports_and_time(state, df_5m)

if __name__ == "__main__":
    main()
