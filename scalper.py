import os
import json
import time
import smtplib
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

import pytz
import yfinance as yf
import pandas as pd
import ta
import requests
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

STATE_FILE = "trade_state.json"
DATA_LOG_FILE = "trade_history.json"

ADMIN_EMAIL_ADDRESS = "Shinos99@gmail.com"
ADMIN_EMAIL_PASSWORD = "Qm1mu8xU"

TELEGRAM_TOKENS = [
    "8830008372:AAEUpi-Pw0BA2aInmc6BonloWLUZ0nuB8i8"
]

# Admin, Secondary & SAS VIP ALERTS Group
TELEGRAM_CHAT_IDS = [
    "8996427731",
    "6789591588",
    "-1004399032148"
]

IST = pytz.timezone('Asia/Kolkata')
TARGET_PTS = 30.0
SL_PTS = 30.0

# ----------------- TELEGRAM & EMAIL FUNCTIONS -----------------
def send_telegram(message, admin_only=False):
    target_chats = [TELEGRAM_CHAT_IDS[0]] if admin_only else TELEGRAM_CHAT_IDS
    formatted_msg = f"⚡ *SAS LEVEL TRACKER* ⚡\n\n{message}"

    for token in TELEGRAM_TOKENS:
        for cid in target_chats:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": cid,
                "text": formatted_msg,
                "parse_mode": "Markdown"
            }
            try:
                requests.post(url, json=payload, timeout=8)
            except Exception as e:
                print(f"Telegram Error: {e}")

def send_telegram_file(file_path, caption):
    caption_text = f"📊 *SAS LEVEL TRACKER*\n{caption}"
    for token in TELEGRAM_TOKENS:
        for cid in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            post_data = {
                "chat_id": cid,
                "caption": caption_text,
                "parse_mode": "Markdown"
            }
            try:
                with open(file_path, 'rb') as f:
                    requests.post(url, data=post_data, files={'document': f}, timeout=20)
            except Exception as e:
                print(f"Telegram File Send Error: {e}")

def send_email_with_pdf(file_path, subject):
    msg = MIMEMultipart()
    msg['From'] = ADMIN_EMAIL_ADDRESS
    msg['To'] = ADMIN_EMAIL_ADDRESS
    msg['Subject'] = f"SAS LEVEL TRACKER - {subject}"
    msg.attach(MIMEText("Please find attached the trading performance report.", 'plain'))

    try:
        with open(file_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
            msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(ADMIN_EMAIL_ADDRESS, ADMIN_EMAIL_PASSWORD)
        server.sendmail(ADMIN_EMAIL_ADDRESS, ADMIN_EMAIL_ADDRESS, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Email Dispatch Error: {e}")

# ----------------- BACKUP & RESTORE -----------------
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
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def log_trade(trade_record):
    trades = []
    if os.path.exists(DATA_LOG_FILE):
        try:
            with open(DATA_LOG_FILE, "r") as f:
                trades = json.load(f)
        except Exception:
            trades = []
    trades.append(trade_record)
    with open(DATA_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=4)

# ----------------- PIVOT LEVELS -----------------
def get_daily_levels():
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

# ----------------- PDF ENGINE -----------------
def generate_pdf(report_type="Daily"):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    pdf_filename = f"{report_type}_Report_{today_str}.pdf"
    
    trades = []
    if os.path.exists(DATA_LOG_FILE):
        with open(DATA_LOG_FILE, "r") as f:
            all_trades = json.load(f)
            if report_type == "Daily":
                trades = [t for t in all_trades if t.get('date') == today_str]
            else:
                curr_month = datetime.now(IST).strftime("%Y-%m")
                trades = [t for t in all_trades if str(t.get('date', '')).startswith(curr_month)]

    doc = SimpleDocTemplate(pdf_filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("<b>SAS LEVEL TRACKER</b>", styles['Title']),
        Paragraph(f"<b>{report_type} Performance Report ({today_str})</b>", styles['Heading2']),
        Spacer(1, 15)
    ]

    table_data = [["Time", "Type", "Entry", "Exit", "Status / Reason", "P&L (Pts)"]]
    total_pts = 0.0

    for t in trades:
        entry = float(t.get('entry', 0.0))
        exit_p = float(t.get('exit', 0.0))
        pnl = round(exit_p - entry if t.get('type') == 'BUY' else entry - exit_p, 2)
        total_pts += pnl

        table_data.append([
            t.get('time', ''),
            t.get('type', ''),
            f"{entry:.2f}",
            f"{exit_p:.2f}",
            t.get('reason', ''),
            f"{pnl:+} pts"
        ])

    table_data.append(["", "", "", "", "Net Points P&L", f"{round(total_pts, 2):+} pts"])

    table = Table(table_data, colWidths=[55, 50, 65, 65, 175, 75])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#ECF0F1")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold')
    ]))
    elements.append(table)
    doc.build(elements)
    return pdf_filename

def is_monthly_expiry_today():
    today = datetime.now(IST).date()
    days_left = 31 - today.day
    if days_left <= 7:
        for d in range(1, days_left + 1):
            future_day = today + timedelta(days=d)
            if future_day.month == today.month and future_day.weekday() == 3:
                return False
        if today.weekday() in [1, 2, 3]:
            return True
    return False

# ----------------- MAIN ENGINE -----------------
def run_trading_bot():
    state = load_state()
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")

    if state.get("last_trade_date") != today_date_str:
        state["today_trade_count"] = 0
        state["last_trade_date"] = today_date_str
        state["sr_sent"] = False
        save_state(state)

    start_time_str = datetime.now(IST).strftime("%I:%M %p")
    send_telegram(f"🤖 *Bot Started / Reconnected*\nTime: `{start_time_str}`\n2-Min Balanced Engine (50 EMA + ADX > 15) Active.", admin_only=True)
    print(f"SAS LEVEL TRACKER System Running at {start_time_str}...")

    while True:
        now = datetime.now(IST)
        current_time_str = now.strftime("%H:%M")

        if now.weekday() >= 5:
            time.sleep(60)
            continue

        # 1. 09:05 AM - Nifty Daily Support & Resistance
        if current_time_str >= "09:05" and not state.get("sr_sent"):
            p, r1, r2, s1, s2 = get_daily_levels()
            msg = (
                f"📈 *NIFTY 50 DAILY LEVELS*\n\n"
                f"🔴 Resistance 2 (R2): `{r2}`\n"
                f"🔴 Resistance 1 (R1): `{r1}`\n"
                f"⚪ Pivot Point: `{p}`\n"
                f"🟢 Support 1 (S1): `{s1}`\n"
                f"🟢 Support 2 (S2): `{s2}`"
            )
            send_telegram(msg, admin_only=False)
            state["sr_sent"] = True
            save_state(state)

        # 2. 09:20 AM to 02:45 PM - Balanced 2-Minute Scalping Engine
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

                    buy_trigger = (
                        ltp > ema_50_val
                        and adx_val > 15.0
                        and prev['ema_9'] <= prev['ema_21']
                        and curr['ema_9'] > curr['ema_21']
                        and rsi > 50
                        and state.get("last_signal_time") != bar_time
                    )

                    sell_trigger = (
                        ltp < ema_50_val
                        and adx_val > 15.0
                        and prev['ema_9'] >= prev['ema_21']
                        and curr['ema_9'] < curr['ema_21']
                        and rsi < 50
                        and state.get("last_signal_time") != bar_time
                    )

                    # ----- ACTIVE TRADE MONITORING -----
                    if trade:
                        if trade['type'] == "BUY":
                            if ltp >= trade['target']:
                                pnl = round(ltp - trade['entry'], 2)
                                log_trade({
                                    "date": today_date_str,
                                    "time": current_time_str,
                                    "type": "BUY",
                                    "entry": trade['entry'],
                                    "exit": ltp,
                                    "reason": "Target 30 Hit",
                                    "pnl": pnl
                                })
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🎯 *TARGET HIT (+30 PTS) (BUY)*\n\n💰 Exit Price: `{ltp}`\n📈 PnL: `+{pnl} pts` 🚀")

                            elif ltp <= trade['sl']:
                                pnl = round(ltp - trade['entry'], 2)
                                log_trade({
                                    "date": today_date_str,
                                    "time": current_time_str,
                                    "type": "BUY",
                                    "entry": trade['entry'],
                                    "exit": ltp,
                                    "reason": "Stop Loss 30 Hit",
                                    "pnl": pnl
                                })
                                state['trade'] = None
                                save_state(state)
                                send_telegram(f"🛑 *STOP LOSS HIT (-30 PTS) (BUY)*\n\nExit Price: `{ltp}`\n📉 PnL
