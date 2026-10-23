import os
import sys
import json
import time
import smtplib
import calendar
import requests
import subprocess
import numpy as np
import pandas as pd
import ta
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
BOT_TOKEN = "8830008372:AAGaq16u0STxZR1Z9q3qO5Lr1MQD288_9pc"
TELEGRAM_CHAT_IDS = [
    "8996427731",
    "6789591588",
    "-1004399032148"
]

ADMIN_EMAIL = "Shinos99@gmail.com"
GMAIL_APP_PASS = "Qm1mu8xU" # Note: Ensure this is a valid Gmail App Password if using 2FA

STATE_FILE = "trade_state.json"
DATA_LOG_FILE = "trade_history.json"
IST = pytz.timezone("Asia/Kolkata")

TARGET_PTS = 30.0
SL_PTS = 30.0

# NSE Holidays for 2026
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

# ================= 3. TELEGRAM & EMAIL UTILS =================
def send_telegram(message, admin_only=False):
    target_chats = [TELEGRAM_CHAT_IDS[0]] if admin_only else TELEGRAM_CHAT_IDS
    formatted_msg = f"⚡ *SAS LEVEL TRACKER* ⚡\n\n{message}"
    for cid in target_chats:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": cid, "text": formatted_msg, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Error: {e}")

def send_telegram_file(file_path, caption):
    caption_text = f"📊 *SAS LEVEL TRACKER*\n{caption}"
    for cid in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        post_data = {"chat_id": cid, "caption": caption_text, "parse_mode": "Markdown"}
        try:
            with open(file_path, 'rb') as f:
                requests.post(url, data=post_data, files={'document': f}, timeout=25)
        except Exception as e:
            print(f"Telegram File Send Error: {e}")

def send_email_with_pdf(file_path, subject):
    try:
        msg = MIMEMultipart()
        msg['From'] = ADMIN_EMAIL
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"SAS LEVEL TRACKER - {subject}"
        msg.attach(MIMEText("Please find attached the trading performance report.", 'plain'))
        
        with open(file_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
            msg.attach(part)
            
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(ADMIN_EMAIL, GMAIL_APP_PASS.replace(" ", ""))
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())
        server.quit()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email Dispatch Error: {e}")

# ================= 4. STATE & GITHUB BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "trade": None,
        "sr_sent": False,
        "heartbeat_sent": False,
        "last_signal_time": "",
        "today_trade_count": 0,
        "last_trade_date": ""
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"State Save Error: {e}")

def git_commit_push(filename):
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "SAS Trading Bot"], check=True)
        subprocess.run(["git", "add", filename], check=True)
        subprocess.run(["git", "commit", "-m", f"Auto-backup: update {filename}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"Successfully committed and pushed {filename} to GitHub.")
    except Exception as e:
        print(f"Git auto-commit failed: {e}")

def log_trade(trade_record):
    trades = []
    if os.path.exists(DATA_LOG_FILE):
        try:
            with open(DATA_LOG_FILE, "r") as f:
                trades = json.load(f)
        except Exception:
            trades = []
    trades.append(trade_record)
    try:
        with open(DATA_LOG_FILE, "w") as f:
            json.dump(trades, f, indent=4)
        git_commit_push(DATA_LOG_FILE)
    except Exception as e:
        print(f"Log Save Error: {e}")

def get_daily_levels():
    try:
        df = yf.download('^NSEI', period='5d', interval='1d', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prev = df.iloc[-2]
        h, l, c = prev['High'], prev['Low'], prev['Close']
        pivot = (h + l + c) / 3
        r1 = (2 * pivot) - l
        s1 = (2 * pivot) - h
        r2 = pivot + (h - l)
        s2 = pivot - (h - l)
        return round(pivot, 2), round(r1, 2), round(r2, 2), round(s1, 2), round(s2, 2)
    except Exception as e:
        print(f"Pivot calculation error: {e}")
        return 0.0, 0.0, 0.0, 0.0, 0.0

# ================= 5. REPORT GENERATION =================
def generate_pdf(report_type="Daily"):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    pdf_filename = f"{report_type}_Report_{today_str}.pdf"
    trades = []
    
    if os.path.exists(DATA_LOG_FILE):
        try:
            with open(DATA_LOG_FILE, "r") as f:
                all_trades = json.load(f)
                if report_type == "Daily":
                    trades = [t for t in all_trades if t.get('date') == today_str]
                else:
                    curr_month = datetime.now(IST).strftime("%Y-%m")
                    trades = [t for t in all_trades if str(t.get('date', '')).startswith(curr_month)]
        except Exception as e:
            print(f"Error reading log file for PDF: {e}")

    doc = SimpleDocTemplate(pdf_filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("<b>SAS LEVEL TRACKER</b>", styles['Title']),
        Paragraph(f"<b>{report_type} Performance Report ({today_str})</b>", styles['Heading2']),
        Spacer(1, 15)
    ]

    table_data = [["Time", "Signal", "Strike", "Entry", "Exit", "Reason", "P&L (Pts)"]]
    total_pts = 0.0

    if not trades:
        table_data.append(["-", "No Trades", "-", "-", "-", "No Trades Recorded", "-"])
    else:
        for t in trades:
            entry = float(t.get('entry', 0.0))
            exit_p = float(t.get('exit', 0.0))
            pnl = float(t.get('pnl', 0.0))
            total_pts += pnl
            table_data.append([
                t.get('time', ''),
                t.get('type', ''),
                t.get('strike', '-'),
                f"Rs.{entry:.2f}",
                f"Rs.{exit_p:.2f}",
                t.get('reason', ''),
                f"{pnl:+} pts"
            ])

    table_data.append(["", "", "", "", "", "Net Points P&L", f"{round(total_pts, 2):+} pts"])
    table = Table(table_data, colWidths=[55, 50, 75, 65, 65, 115, 75])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#ECF0F1")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold')
    ]))
    elements.append(table)
    doc.build(elements)
    return pdf_filename

# ================= 6. MAIN TRADING BOT ENGINE =================
def run_trading_bot():
    state = load_state()
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")
    now_ist = datetime.now(IST)
    weekday = now_ist.weekday()

    if weekday >= 5:
        print("Weekend detected. Exiting.")
        sys.exit(0)

    if today_date_str in NSE_HOLIDAYS_2026:
        print(f"Holiday today: {NSE_HOLIDAYS_2026[today_date_str]}. Exiting.")
        sys.exit(0)

    if state.get("last_trade_date") != today_date_str:
        state["today_trade_count"] = 0
        state["last_trade_date"] = today_date_str
        state["sr_sent"] = False
        state["daily_report_sent"] = False
        save_state(state)

    start_time_str = now_ist.strftime("%I:%M %p")
    start_msg = f"""🤖 *Bot Started Successfully*
Time: `{start_time_str}`
Continuous Scalping Engine (09:00 AM - 03:40 PM) Active."""
    send_telegram(start_msg, admin_only=True)
    print(f"SAS LEVEL TRACKER System Running at {start_time_str}...")

    while True:
        now = datetime.now(IST)
        current_time_str = now.strftime("%H:%M")

        # 09:05 AM Support & Resistance Levels
        if "09:05" <= current_time_str < "09:10" and not state.get("sr_sent"):
            p, r1, r2, s1, s2 = get_daily_levels()
            if p > 0:
                msg = f"""📈 *NIFTY 50 DAILY LEVELS*

🔴 Resistance 2 (R2): `{r2}`
🔴 Resistance 1 (R1): `{r1}`
⚪ Pivot Point: `{p}`
🟢 Support 1 (S1): `{s1}`
🟢 Support 2 (S2): `{s2}`"""
                send_telegram(msg, admin_only=False)
                state["sr_sent"] = True
                save_state(state)

        # 09:15 AM to 03:20 PM - Continuous Engine Execution
        if "09:15" <= current_time_str < "15:20":
            try:
                df = yf.download('^NSEI', period='5d', interval='2m', progress=False)
                if not df.empty and len(df) >= 55:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)

                    df['ema_9'] = ta.trend.ema_indicator(df['Close'], window=9)
                    df['ema_21'] = ta.trend.ema_indicator(df['Close'], window=21)
                    df['ema_50'] = ta.trend.ema_indicator(df['Close'], window=50)
                    df['rsi'] = ta.momentum.rsi(df['Close'], window=14)
                    
                    adx_indicator = ta.trend.ADXIndicator(df['High'], df['Low'], df['Close'], window=14)
                    df['adx'] = adx_indicator.adx()

                    curr = df.iloc[-1]
                    prev = df.iloc[-2]
                    ltp = round(curr['Close'], 2)
                    rsi = round(curr['rsi'], 2)
                    adx_val = round(curr['adx'], 2)
                    ema_50_val = round(curr['ema_50'], 2)
                    bar_time = str(df.index[-1])

                    trade = state.get("trade")
                    is_trading_window = "09:20" <= current_time_str <= "14:45"

                    atm_strike = round(ltp / 50.0) * 50

                    buy_trigger = (
                        ltp > ema_50_val
                        and adx_val > 15.0
                        and prev['ema_9'] <= prev['ema_21'] and curr['ema_9'] > curr['ema_21']
                        and rsi > 50
                        and state.get("last_signal_time") != bar_time
                    )

                    sell_trigger = (
                        ltp < ema_50_val
                        and adx_val > 15.0
                        and prev['ema_9'] >= prev['ema_21'] and curr['ema_9'] < curr['ema_21']
                        and rsi < 50
                        and state.get("last_signal_time") != bar_time
                    )

                    # ----- ACTIVE TRADE MONITORING -----
                    if trade:
                        strike = trade.get('strike', f"{atm_strike} CE")
                        if trade['type'] == "BUY":
                            if ltp >= trade['target']:
                                pnl = round(ltp - trade['entry'], 2)
                                log_trade({"date": today_date_str, "time": current_time_str, "type": "BUY", "strike": strike, "entry": trade['entry'], "exit": ltp, "reason": "Target 30 Hit", "pnl": pnl})
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🎯 *TARGET HIT (+30 PTS) (BUY)*\n• Strike: `{strike}`\n• Exit Price: `{ltp}`\n• PnL: `+{pnl} pts` 🚀")

                            elif ltp <= trade['sl']:
                                pnl = round(ltp - trade['entry'], 2)
                                log_trade({"date": today_date_str, "time": current_time_str, "type": "BUY", "strike": strike, "entry": trade['entry'], "exit": ltp, "reason": "Stop Loss 30 Hit", "pnl": pnl})
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🛑 *STOP LOSS HIT (-30 PTS) (BUY)*\n• Strike: `{strike}`\n• Exit Price: `{ltp}`\n• PnL: `{pnl} pts`")

                        elif trade['type'] == "SELL":
                            if ltp <= trade['target']:
                                pnl = round(trade['entry'] - ltp, 2)
                                log_trade({"date": today_date_str, "time": current_time_str, "type": "SELL", "strike": strike, "entry": trade['entry'], "exit": ltp, "reason": "Target 30 Hit", "pnl": pnl})
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🎯 *TARGET HIT (+30 PTS) (SELL)*\n• Strike: `{strike}`\n• Exit Price: `{ltp}`\n• PnL: `+{pnl} pts` 🚀")

                            elif ltp >= trade['sl']:
                                pnl = round(trade['entry'] - ltp, 2)
                                log_trade({"date": today_str, "time": current_time_str, "type": "SELL", "strike": strike, "entry": trade['entry'], "exit": ltp, "reason": "Stop Loss 30 Hit", "pnl": pnl})
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🛑 *STOP LOSS HIT (-30 PTS) (SELL)*\n• Strike: `{strike}`\n• Exit Price: `{ltp}`\n• PnL: `{pnl} pts`")

                    # ----- ENTRY TRIGGER -----
                    if state.get("trade") is None and is_trading_window:
                        if buy_trigger:
                            strike = f"{atm_strike} CE"
                            target = round(ltp + TARGET_PTS, 2)
                            sl = round(ltp - SL_PTS, 2)
                            state['trade'] = {"type": "BUY", "strike": strike, "entry": ltp, "target": target, "sl": sl}
                            state['last_signal_time'] = bar_time
                            state['today_trade_count'] = state.get("today_trade_count", 0) + 1
                            save_state(state)
                            trade_no = state['today_trade_count']
                            send_telegram(f"🟢 *NEW SIGNAL: BUY NIFTY (Trade #{trade_no})*\n• Option Strike: `{strike}`\n• Spot Entry: `{ltp}`\n• Target (+30): `{target}`\n• Stop Loss (-30): `{sl}`")

                        elif sell_trigger:
                            strike = f"{atm_strike} PE"
                            target = round(ltp - TARGET_PTS, 2)
                            sl = round(ltp + SL_PTS, 2)
                            state['trade'] = {"type": "SELL", "strike": strike, "entry": ltp, "target": target, "sl": sl}
                            state['last_signal_time'] = bar_time
                            state['today_trade_count'] = state.get("today_trade_count", 0) + 1
                            save_state(state)
                            trade_no = state['today_trade_count']
                            send_telegram(f"🔴 *NEW SIGNAL: SELL NIFTY (Trade #{trade_no})*\n• Option Strike: `{strike}`\n• Spot Entry: `{ltp}`\n• Target (-30): `{target}`\n• Stop Loss (+30): `{sl}`")

            except Exception as e:
                print(f"Loop runtime error: {e}")

        # 03:20 PM - Auto Square-off
        if current_time_str >= "15:20" and state.get("trade"):
            try:
                df = yf.download('^NSEI', period='1d', interval='1m', progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                ltp = round(df.iloc[-1]['Close'], 2)
            except Exception:
                ltp = state['trade']['entry']

            trade = state['trade']
            strike = trade.get('strike', '-')
            pnl = round((ltp - trade['entry']) if trade['type'] == "BUY" else (trade['entry'] - ltp), 2)
            log_trade({
                "date": today_date_str,
                "time": current_time_str,
                "type": trade['type'],
                "strike": strike,
                "entry": trade['entry'],
                "exit": ltp,
                "reason": "Intraday Auto Square-off (3:20 PM)",
                "pnl": pnl
            })
            send_telegram(f"⏰ *INTRADAY AUTO-SQUARE OFF (3:20 PM)*\n• Position: `{trade['type']} NIFTY`\n• Strike: `{strike}`\n• Entry: `{trade['entry']}`\n• Exit: `{ltp}`\n• PnL: `{pnl:+} pts`")
            state['trade'] = None
            save_state(state)

        # 03:40 PM - Daily & Monthly Reports Dispatched to Telegram & Email
        if current_time_str >= "15:40" and not state.get("daily_report_sent"):
            daily_pdf = generate_pdf("Daily")
            send_telegram_file(daily_pdf, "Daily Trading Performance Report")
            send_email_with_pdf(daily_pdf, "Daily P&L Report")

            if is_monthly_expiry_today():
                monthly_pdf = generate_pdf("Monthly")
                send_telegram_file(monthly_pdf, "Monthly Expiry Detailed P&L Report")
                send_email_with_pdf(monthly_pdf, "Monthly Expiry Detailed Report")

            state["daily_report_sent"] = True
            save_state(state)
            print("Today's operations completed successfully.")
            break

        time.sleep(15)

if __name__ == "__main__":
    run_trading_bot()
