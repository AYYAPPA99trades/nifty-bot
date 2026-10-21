import os
import sys
import json
import time
import smtplib
import calendar
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, date, timedelta, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

# ReportLab for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ================= 1. CREDENTIALS & CONSTANTS =================
BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8"
ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "-1004416495917"

ADMIN_EMAIL = "shinos99@gmail.com"
GMAIL_APP_PASS = "wgms etgl eklv cdja"

STATE_FILE = "sas_bot_state.json"
HISTORY_FILE = "sas_expiry_cycle_trades.json"
IST = pytz.timezone("Asia/Kolkata")

# NSE Holidays with Reason
NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Ram Navami",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day / Labour Day",
    "2026-08-15": "Independence Day",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Balipratipada",
    "2026-12-25": "Christmas"
}

# ================= 2. MONTHLY EXPIRY CALCULATOR =================
def get_monthly_expiry_date(year, month):
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)

    target_weekday = 3  # Thursday
    while d.weekday() != target_weekday:
        d -= timedelta(days=1)

    while d.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026 or d.weekday() >= 5:
        d -= timedelta(days=1)

    return d

def is_today_monthly_expiry():
    today = datetime.now(IST).date()
    expiry_date = get_monthly_expiry_date(today.year, today.month)
    return today == expiry_date

# ================= 3. DATA FETCH (YAHOO FINANCE - 1 MIN SCALPING) =================
def get_nifty_candle_data():
    try:
        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period="2d", interval="1m")
        if df is not None and not df.empty:
            df = df.reset_index()
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df = df.rename(columns={time_col: "Timestamp", "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            if df["Timestamp"].dt.tz is not None:
                df["Timestamp"] = df["Timestamp"].dt.tz_convert(IST)
            else:
                df["Timestamp"] = df["Timestamp"].dt.tz_localize("UTC").dt.tz_convert(IST)
            
            df.set_index("Timestamp", inplace=True)
            df.index = df.index.tz_localize(None)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        return None
    except Exception as e:
        print(f"Data Fetch Exception: {e}")
        return None

# ================= 4. TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n"
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    try:
        res = requests.post(
            url, 
            json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
            timeout=10
        )
        data = res.json()
        if not data.get("ok"):
            print(f"Telegram Admin Error [{res.status_code}]: {data.get('description')}")
    except Exception as e:
        print(f"Telegram Admin Connection Error: {e}")

    if target == "all" and CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):
        try:
            requests.post(
                url, 
                json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
                timeout=10
            )
        except Exception as e:
            print(f"Telegram Channel Error: {e}")

# ================= 5. STATE & CRASH BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_trade": None,
        "support_sent_today": False,
        "daily_report_sent_today": False,
        "monthly_report_sent_today": False,
        "startup_alert_sent": False,
        "last_hourly_alert_hour": None
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def log_trade(trade_record):
    trades = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                trades = json.load(f)
        except Exception:
            trades = []
    trades.append(trade_record)
    with open(HISTORY_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def clear_expiry_cycle_trades():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            json.dump([], f)

# ================= 6. PDF & EMAIL REPORT =================
def generate_pdf_report(filename, title, subtitle, trades):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1A365D"), spaceAfter=10)
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 15))

    table_data = [["Date", "Signal", "Entry Price", "Exit Price", "P&L (Points)", "Reason", "Time"]]
    total_points = 0.0

    if not trades:
        table_data.append(["-", "No Trades", "-", "-", "-", "-", "-"])
    else:
        for t in trades:
            pts = round(t["pnl_points"], 2)
            total_points += pts
            table_data.append([
                t.get("date", "-"),
                t["action"],
                f"Rs.{t['entry']}",
                f"Rs.{t['exit']}",
                f"{'+' if pts > 0 else ''}{pts}",
                t["reason"],
                t["exit_time"]
            ])

    t = Table(table_data, colWidths=[70, 60, 80, 80, 85, 120, 60])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 20))

    summary_text = f"<b>Net Cumulative P&L (Strict Entry to Exit):</b> {'+' if total_points > 0 else ''}{round(total_points, 2)} Points"
    elements.append(Paragraph(summary_text, styles["Heading2"]))
    doc.build(elements)
    return filename

def send_email_with_attachment(pdf_path, subject, body_text):
    try:
        msg = MIMEMultipart()
        msg["From"] = ADMIN_EMAIL
        msg["To"] = ADMIN_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))

        with open(pdf_path, "rb") as attachment:
            p = MIMEBase("application", "octet-stream")
            p.set_payload(attachment.read())
            encoders.encode_base64(p)
            p.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(pdf_path)}")
            msg.attach(p)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(ADMIN_EMAIL, GMAIL_APP_PASS.replace(" ", ""))
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent successfully: {subject}")
    except Exception as e:
        print(f"Failed to send email: {e}")

# ================= 7. SCALPING INDICATORS =================
def calculate_indicators(df):
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    hl2 = (df["High"] + df["Low"]) / 2
    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift())
    low_close = np.abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(10).mean()
    df["ATR"] = atr

    upper_basic = hl2 + (3 * atr)
    lower_basic = hl2 - (3 * atr)
    upper_band = [0.0] * len(df)
    lower_band = [0.0] * len(df)
    supertrend = [True] * len(df)

    for i in range(10, len(df)):
        if upper_basic.iloc[i] < upper_band[i-1] or df["Close"].iloc[i-1] > upper_band[i-1]:
            upper_band[i] = upper_basic.iloc[i]
        else:
            upper_band[i] = upper_band[i-1]

        if lower_basic.iloc[i] > lower_band[i-1] or df["Close"].iloc[i-1] < lower_band[i-1]:
            lower_band[i] = lower_basic.iloc[i]
        else:
            lower_band[i] = lower_band[i-1]

        if i == 10:
            supertrend[i] = True if df["Close"].iloc[i] > upper_basic.iloc[i] else False
        else:
            if supertrend[i-1]:
                supertrend[i] = False if df["Close"].iloc[i] < lower_band[i] else True
            else:
                supertrend[i] = True if df["Close"].iloc[i] > upper_band[i] else False

    df["Supertrend"] = supertrend
    return df

# ================= 8. INTRADAY SCALPING SCANNER =================
def process_market_cycle(state):
    now_ist = datetime.now(IST)
    curr_time = now_ist.time()
    today_str = now_ist.strftime("%Y-%m-%d")

    if dtime(9, 0) <= curr_time < dtime(9, 5):
        if not state.get("startup_alert_sent"):
            send_telegram("🚀 *MARKET SESSION START (9:00 AM):*\nIntraday 1-Min Scalping Bot Active.", target="admin")
            state["startup_alert_sent"] = True
            save_state(state)

    df = get_nifty_candle_data()
    if df is None or len(df) < 30:
        return

    df = calculate_indicators(df)

    if dtime(9, 5) <= curr_time < dtime(9, 15):
        if not state.get("support_sent_today"):
            c_spot = round(float(df.iloc[-1]["Close"]), 2)
            msg = (
                f"📊 *NIFTY SCALPING LIVE FEED (9:05 AM)*\n\n"
                f"• *Current Spot:* Rs.{c_spot}\n"
                f"• *Strategy:* 1-Min Scalping (EMA + RSI + Supertrend)"
            )
            send_telegram(msg, target="all")
            state["support_sent_today"] = True
            save_state(state)

    if 10 <= now_ist.hour <= 15:
        if state.get("last_hourly_alert_hour") != now_ist.hour:
            c_spot = round(float(df.iloc[-1]["Close"]), 2)
            active = state.get("active_trade")
            if active:
                trade_info = f"`{active['action']}` (Entry: Rs.{active['entry']} | {'T1 Secured 🎯' if active['t1_hit'] else 'Active SL: Rs.' + str(active['spot_sl'])})"
            else:
                trade_info = "None (Scanning 1-Min Setup)"

            trades_cnt = 0
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        h_trades = json.load(f)
                        trades_cnt = len([t for t in h_trades if t.get("date") == today_str])
                except Exception:
                    pass

            hourly_msg = (
                f"⏱ *HOURLY SCALPING UPDATE ({now_ist.strftime('%I:00 %p')})*\n\n"
                f"🟢 *Bot Health:* Active (1-Min Scalping)\n"
                f"📈 *Nifty Spot:* Rs.{c_spot}\n"
                f"🔄 *Active Trade:* {trade_info}\n"
                f"📑 *Today's Scalps Closed:* {trades_cnt}"
            )
            send_telegram(hourly_msg, target="admin")
            state["last_hourly_alert_hour"] = now_ist.hour
            save_state(state)

    if dtime(9, 15) <= curr_time <= dtime(15, 20):
        candle = df.iloc[-1]
        c_close = float(candle["Close"])
        c_high = float(candle["High"])
        c_low = float(candle["Low"])
        c_atr = float(candle["ATR"]) if not np.isnan(candle["ATR"]) else 15.0
        c_ema9 = float(candle["EMA9"])
        c_ema21 = float(candle["EMA21"])
        c_rsi = float(candle["RSI"]) if not np.isnan(candle["RSI"]) else 50.0
        c_st = bool(candle["Supertrend"])

        active = state.get("active_trade")

        if active is not None:
            if not active["t1_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t1"]) or (active["action"] == "SELL" and c_low <= active["spot_t1"]):
                    active["t1_hit"] = True
                    active["sl_active"] = False
                    msg = (
                        f"🎯 *SAS ALERT: TARGET 1 (T1) ACHIEVED!*\n"
                        f"• Spot T1 Hit (Rs.{active['spot_t1']})\n"
                        f"• Option T1 Hit: **Approx Rs.{active['opt_t1']}**\n"
                        f"• Trade Secured: **Stop Loss Removed**."
                    )
                    send_telegram(msg, target="all")
                    save_state(state)

            if active["t1_hit"] and not active["t2_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t2"]) or (active["action"] == "SELL" and c_low <= active["spot_t2"]):
                    active["t2_hit"] = True
                    send_telegram(f"🚀 *SAS ALERT: TARGET 2 (T2) ACHIEVED!*\n• Spot T2 Hit (Rs.{active['spot_t2']})\n• Option T2 Hit: **Approx Rs.{active['opt_t2']}**", target="all")
                    save_state(state)

            if active["t2_hit"] and not active["t3_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t3"]) or (active["action"] == "SELL" and c_low <= active["spot_t3"]):
                    active["t3_hit"] = True
                    exit_price = active["spot_t3"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🏆 *SAS ALERT: FINAL TARGET 3 (T3) HIT!*\n• Spot T3 Hit (Rs.{active['spot_t3']})\n• Option T3 Hit: **Approx Rs.{active['opt_t3']}**", target="all")
                    
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Target 3 Achieved",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    return

            if active["sl_active"]:
                sl_hit = (active["action"] == "BUY" and c_low <= active["spot_sl"]) or (active["action"] == "SELL" and c_high >= active["spot_sl"])
                if sl_hit:
                    exit_price = active["spot_sl"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🛑 *SAS ALERT: STOP LOSS HIT!*\n• Spot SL Hit (Rs.{active['spot_sl']})\n• Option SL Hit: **Approx Rs.{active['opt_sl']}**", target="all")
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Stop Loss Hit",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    return

        # Scalping Entry Signals with Trend Reversal Logic
        new_signal = None
        if c_ema9 > c_ema21 and c_st and c_rsi > 52:
            new_signal = "BUY"
        elif c_ema9 < c_ema21 and not c_st and c_rsi < 48:
            new_signal = "SELL"

        if new_signal:
            if active is not None:
                if active["action"] != new_signal:
                    exit_price = c_close
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🔄 *SAS ALERT: TREND REVERSAL ({new_signal}):* Exit previous `{active['action']}` trade at Rs.{exit_price} and switch position.", target="all")
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": f"Trend Reversal to {new_signal}",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    trigger_entry(new_signal, c_close, c_atr, now_ist, state)
            else:
                trigger_entry(new_signal, c_close, c_atr, now_ist, state)

    # 3:20 PM Auto Square Off
    if dtime(15, 20) <= curr_time < dtime(15, 25):
        if state.get("active_trade") is not None:
            active = state["active_trade"]
            exit_price = round(float(df.iloc[-1]["Close"]), 2)
            pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
            
            sq_msg = (
                f"⏰ *SAS ALERT: INTRADAY AUTO-SQUARE OFF (3:20 PM)*\n\n"
                f"• *Position:* {active['action']} NIFTY\n"
                f"• *Entry Price:* Rs.{active['entry']}\n"
                f"• *Exit Price:* Rs.{exit_price}\n"
                f"• *PnL:* {'+' if pnl > 0 else ''}{round(pnl, 2)} pts"
            )
            send_telegram(sq_msg, target="all")
            
            log_trade({
                "date": today_str, "action": active["action"],
                "entry": active["entry"], "exit": exit_price,
                "pnl_points": pnl, "reason": "Intraday Close (3:20 PM)",
                "exit_time": now_ist.strftime("%H:%M")
            })
            state["active_trade"] = None
            save_state(state)

    # 3:25 PM Daily P&L PDF Report & Email
    if dtime(15, 25) <= curr_time < dtime(15, 30):
        if not state.get("daily_report_sent_today"):
            all_trades = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        all_trades = json.load(f)
                except Exception:
                    pass
            today_trades = [t for t in all_trades if t.get("date") == today_str]

            pdf_filename = f"SAS_Daily_Report_{today_str}.pdf"
            generate_pdf_report(
                pdf_filename,
                f"SAS LEVEL TRACKER - DAILY SCALPING REPORT",
                f"<b>Date:</b> {today_str} | <b>Calculation:</b> Entry to Exit Price",
                today_trades
            )
            send_email_with_attachment(
                pdf_filename,
                f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",
                f"Hello Admin,\n\nPlease find attached the Daily Scalping P&L Report for {today_str}."
            )
            net_pts = sum(t["pnl_points"] for t in today_trades)
            send_telegram(
                f"📄 *SAS ALERT: DAILY P&L REPORT (3:25 PM)*\n\n"
                f"• *Date:* {today_str}\n"
                f"• *Trades Executed:* {len(today_trades)}\n"
                f"• *Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts\n"
                f"Verified PDF sent to Admin email ({ADMIN_EMAIL}).",
                target="all"
            )
            state["daily_report_sent_today"] = True
            save_state(state)

    # 3:30 PM Monthly Expiry Detailed P&L Report
    if dtime(15, 30) <= curr_time < dtime(15, 35):
        if is_today_monthly_expiry() and not state.get("monthly_report_sent_today"):
            all_cycle_trades = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        all_cycle_trades = json.load(f)
                except Exception:
                    pass

            month_str = now_ist.strftime("%B_%Y")
            monthly_pdf = f"SAS_Monthly_Expiry_Report_{month_str}.pdf"
            generate_pdf_report(
                monthly_pdf,
                f"SAS LEVEL TRACKER - MONTHLY EXPIRY DETAILED REPORT",
                f"<b>Expiry Date:</b> {today_str} | <b>Cycle:</b> Expiry to Expiry Detailed P&L",
                all_cycle_trades
            )
            send_email_with_attachment(
                monthly_pdf,
                f"SAS LEVEL TRACKER: Monthly Expiry-to-Expiry Report ({month_str})",
                f"Hello Admin,\n\nToday is Monthly Expiry Day. Attached is the complete Expiry-to-Expiry performance log."
            )
            total_cycle_pts = sum(t["pnl_points"] for t in all_cycle_trades)
            send_telegram(
                f"🏆 *SAS ALERT: MONTHLY EXPIRY REPORT (3:30 PM)*\n\n"
                f"Today marks the Monthly Expiry Day!\n"
                f"• *Total Cycle Trades:* {len(all_cycle_trades)}\n"
                f"• *Total Cycle Net P&L:* {'+' if total_cycle_pts > 0 else ''}{round(total_cycle_pts, 2)} Pts\n"
                f"Detailed Monthly P&L statement dispatched to Admin email.",
                target="all"
            )
            clear_expiry_cycle_trades()
            state["monthly_report_sent_today"] = True
            save_state(state)

def trigger_entry(action, price, atr, now_ist, state):
    sl_dist = max(round(1.0 * atr, 1), 15.0)
    t1_dist = round(sl_dist * 1.0, 1)
    t2_dist = round(sl_dist * 1.8, 1)
    t3_dist = round(sl_dist * 2.8, 1)

    entry = round(price, 2)
    atm_strike = round(entry / 50.0) * 50
    opt_entry = 145.0  # Standard ATM Option Premium for scalping

    if action == "BUY":
        spot_sl = round(entry - sl_dist, 2)
        spot_t1 = round(entry + t1_dist, 2)
        spot_t2 = round(entry + t2_dist, 2)
        spot_t3 = round(entry + t3_dist, 2)
        strike = f"{atm_strike} CE"
        icon = "🟢"

        opt_t1 = round(opt_entry + (t1_dist * 0.6), 1)
        opt_t2 = round(opt_entry + (t2_dist * 0.6), 1)
        opt_t3 = round(opt_entry + (t3_dist * 0.6), 1)
        opt_sl = max(round(opt_entry - (sl_dist * 0.5), 1), 10.0)
    else:
        spot_sl = round(entry + sl_dist, 2)
        spot_t1 = round(entry - t1_dist, 2)
        spot_t2 = round(entry - t2_dist, 2)
        spot_t3 = round(entry - t3_dist, 2)
        strike = f"{atm_strike} PE"
        icon = "🔴"

        opt_t1 = round(opt_entry + (t1_dist * 0.6), 1)
        opt_t2 = round(opt_entry + (t2_dist * 0.6), 1)
        opt_t3 = round(opt_entry + (t3_dist * 0.6), 1)
        opt_sl = max(round(opt_entry - (sl_dist * 0.5), 1), 10.0)

    msg = (
        f"⚡ *SAS ALERT*\n\n"
        f"• *Instrument:* NIFTY 50 (`{strike}`)\n"
        f"• *Action:* {icon} *{action}*\n\n"
        f"🟢 *OPTION DETAILS:*\n"
        f"• *Option Strike:* `{strike}`\n"
        f"• *Option Price (Buy Rate):* ~Rs.{opt_entry}\n"
        f"• *Option Target 1 (T1):* ~Rs.{opt_t1}\n"
        f"• *Option Target 2 (T2):* ~Rs.{opt_t2}\n"
        f"• *Option Target 3 (T3):* ~Rs.{opt_t3}\n"
        f"• *Option Stop Loss (SL):* ~Rs.{opt_sl}\n\n"
        f"📌 *NIFTY SPOT REFERENCE & TARGETS:*\n"
        f"• *Spot Entry:* Rs.{entry}\n"
        f"• *Spot T1:* Rs.{spot_t1}\n"
        f"• *Spot T2:* Rs.{spot_t2}\n"
        f"• *Spot T3:* Rs.{spot_t3}\n"
        f"• *Spot SL:* Rs.{spot_sl}\n"
        f"• *Time:* {now_ist.strftime('%H:%M:%S')} IST"
    )
    send_telegram(msg, target="all")

    state["active_trade"] = {
        "action": action, "entry": entry,
        "spot_t1": spot_t1, "spot_t2": spot_t2, "spot_t3": spot_t3, "spot_sl": spot_sl,
        "opt_entry": opt_entry, "opt_t1": opt_t1, "opt_t2": opt_t2, "opt_t3": opt_t3, "opt_sl": opt_sl,
        "t1_hit": False, "t2_hit": False, "t3_hit": False,
        "sl_active": True, "entry_time": now_ist.strftime("%H:%M")
    }
    save_state(state)

def main():
    print("Starting SAS LEVEL TRACKER Scalping Service...")
    
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    weekday = now_ist.weekday()

    if weekday >= 5:
        day_name = "Saturday" if weekday == 5 else "Sunday"
        send_telegram(
            f"🏖️ *WEEKEND PAUSE ({day_name})*\n\n"
            f"Market is closed today. Live scanner is inactive.\n"
            f"Workflow stopped immediately to save minutes.",
            target="admin"
        )
        print("Weekend detected. Workflow exited.")
        sys.exit(0)

    if today_str in NSE_HOLIDAYS_2026:
        reason = NSE_HOLIDAYS_2026[today_str]
        holiday_msg = (
            f"🏖️ *MARKET HOLIDAY ALERT (NSE/BSE)*\n\n"
            f"• *Date:* {today_str}\n"
            f"• *Occasion:* *{reason}*\n"
            f"• *Status:* Market is officially closed today.\n"
            f"Live scanner and alerts are paused."
        )
        send_telegram(holiday_msg, target="all")
        print(f"Holiday today: {reason}. Exiting.")
        sys.exit(0)

    send_telegram("🚀 *BOT RUNNING:* 1-Minute Scalping Bot Active.", target="admin")

    state = load_state()

    while True:
        try:
            now_ist = datetime.now(IST)
            curr_time = now_ist.time()

            if curr_time > dtime(15, 40):
                print("Market session completed. Shutting down bot.")
                send_telegram("🛑 *SYSTEM SHUTDOWN (3:40 PM):* Daily session completed.", target="admin")
                break

            if dtime(8, 58) <= curr_time <= dtime(15, 40):
                process_market_cycle(state)
                time.sleep(5)
            else:
                time.sleep(30)

        except Exception as e:
            print(f"Engine Loop Error: {e}")
            time.sleep(10)

    print("Workflow completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()
