import os
import time
import requests
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- FAST DUAL TELEGRAM ENGINE (ZERO DELAY SESSION) ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]
tele_session = requests.Session()

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
            tele_session.post(url, json=payload, timeout=3)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                requests.post(url, data=data, files=files, timeout=15)
        except Exception as e:
            print(f"Telegram Doc Error ({chat_id}): {e}")

# --- EMAIL BACKUP CONFIGURATION ---
SENDER_EMAIL = "shinosanthagopi@gmail.com"
SENDER_APP_PASSWORD = "nouiwuzkyjbzsgix"
RECEIVER_EMAILS = ["shinosanthagopi@gmail.com"]

def send_email_with_pdf(file_path, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ", ".join(RECEIVER_EMAILS)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with open(file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(file_path)}")
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAILS, msg.as_string())
        server.quit()
        print("PDF report emailed successfully.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- 1. WEEKEND PROTECTION ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ *WEEKEND MARKET HOLIDAY ({day_name})!*\n\n"
        f"• Status: Market is Closed.\n"
        f"• Scanner will remain inactive today.\n"
        f"• Resumes Monday at 09:00 AM IST."
    )
    exit(0)

# --- 2. NSE OFFICIAL HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(
                f"🏖️ *MARKET HOLIDAY TODAY!*\n\n"
                f"• Occasion / Reason: *{reason}*\n"
                f"• Status: Live trading closed.\n"
                f"• Bot shutting down cleanly."
            )
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_quantum.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"
STRATEGY_DISPLAY_NAME = "QUANTUM MOMENTUM"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0, "early_cuts": 0}
trade_logs = []
prev_close_dict = {}
camarilla_levels = {}
pivots_alert_sent = False
hero_zero_sent = False
last_heartbeat_hour = -1

# --- JSON PERSISTENCE SYSTEM (STATE BACKUP) ---
def load_backup_state():
    default_state = {idx: None for idx in INDEX_WATCHLIST}
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                for idx in INDEX_WATCHLIST:
                    if idx not in data:
                        data[idx] = None
                return data
        except Exception as err:
            print(f"Backup Load Error: {err}")
    return default_state

def save_backup_state(state):
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as err:
        print(f"Backup Save Error: {err}")

# --- MONTHLY LEDGER PERSISTENCE ---
def record_to_monthly_ledger(log_entry):
    records = []
    if os.path.exists(MONTHLY_LEDGER_FILE):
        try:
            with open(MONTHLY_LEDGER_FILE, 'r') as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append(log_entry)
    try:
        with open(MONTHLY_LEDGER_FILE, 'w') as f:
            json.dump(records, f, indent=4)
    except Exception as e:
        print(f"Ledger save warning: {e}")

# --- CAMARILLA PIVOT CALCULATION (R1-R4 & S1-S4) ---
def calculate_camarilla_pivots(index_name):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_daily = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not df_daily.empty:
            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily.columns = df_daily.columns.get_level_values(0)
            prev_day = df_daily.iloc[-2]
            high = float(prev_day['High'])
            low = float(prev_day['Low'])
            close = float(prev_day['Close'])
            diff = high - low

            r4 = close + (diff * 1.1 / 2.0)
            r3 = close + (diff * 1.1 / 4.0)
            r2 = close + (diff * 1.1 / 6.0)
            r1 = close + (diff * 1.1 / 12.0)

            s1 = close - (diff * 1.1 / 12.0)
            s2 = close - (diff * 1.1 / 6.0)
            s3 = close - (diff * 1.1 / 4.0)
            s4 = close - (diff * 1.1 / 2.0)

            return {
                "R4": round(r4, 2), "R3": round(r3, 2), "R2": round(r2, 2), "R1": round(r1, 2),
                "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2), "S4": round(s4, 2),
                "Prev_Close": round(close, 2)
            }
    except Exception as e:
        print(f"Pivot calc warning ({index_name}): {e}")
    return None

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

active_trades = load_backup_state()

# --- LIVE OPTION STRIKE & ESTIMATED PREMIUM ENGINE ---
def get_option_recommendations(index_name, spot_price, signal_direction, spot_risk):
    step = 50 if index_name == "NIFTY 50" else 100
    atm_strike = int(round(spot_price / step) * step)
    delta = 0.50

    base_atm_price = 110.0 if index_name == "NIFTY 50" else 260.0
    otm_seller_price = 70.0 if index_name == "NIFTY 50" else 170.0

    buyer_entry = base_atm_price
    buyer_sl = max(10.0, round(buyer_entry - (spot_risk * delta), 1))
    buyer_t1 = round(buyer_entry + (spot_risk * 1.0 * delta), 1)
    buyer_t2 = round(buyer_entry + (spot_risk * 1.5 * delta), 1)
    buyer_t3 = round(buyer_entry + (spot_risk * 2.5 * delta), 1)

    seller_entry = base_atm_price
    seller_sl = round(seller_entry + (spot_risk * delta), 1)
    seller_target = max(5.0, round(seller_entry - (spot_risk * 1.2 * delta), 1))

    if signal_direction == "BUY":
        buyer_strike = f"{atm_strike} CE"
        seller_strike = f"{atm_strike} PE"
        safe_seller_strike = f"{atm_strike - step} PE"
    else:
        buyer_strike = f"{atm_strike} PE"
        seller_strike = f"{atm_strike} CE"
        safe_seller_strike = f"{atm_strike + step} CE"

    return {
        "buyer_strike": buyer_strike,
        "buyer_entry": buyer_entry,
        "buyer_sl": buyer_sl,
        "buyer_t1": buyer_t1,
        "buyer_t2": buyer_t2,
        "buyer_t3": buyer_t3,
        "seller_strike": seller_strike,
        "seller_entry": seller_entry,
        "seller_sl": seller_sl,
        "seller_target": seller_target,
        "safe_seller_strike": safe_seller_strike,
        "safe_seller_entry": otm_seller_price
    }

# --- PDF REPORT ENGINE (DAILY & MONTHLY) ---
def generate_pdf_report(filename, title_text, date_str, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        'RepTitle', parent=styles['Heading1'], fontSize=16, leading=20,
        textColor=colors.HexColor("#1A365D"), alignment=1
    )
    elements.append(Paragraph(f"{title_text} ({STRATEGY_DISPLAY_NAME})", title_style))
    elements.append(Paragraph(f"Period/Date: {date_str} | Trading Hours: 09:30 AM - 03:20 PM IST", styles['Normal']))
    elements.append(Spacer(1, 15))

    tot_sig = len(logs_to_print)
    target_count = sum(1 for l in logs_to_print if 'Target' in l.get('status', '') or 'Reversal' in l.get('status', ''))
    sl_count = sum(1 for l in logs_to_print if 'SL Hit' in l.get('status', ''))
    early_count = sum(1 for l in logs_to_print if 'Early Cut' in l.get('status', ''))

    sum_data = [
        ["Total Signals", "Targets / Locks", "Stop Losses Hit", "Early Cuts"],
        [str(tot_sig), str(target_count), str(sl_count), str(early_count)]
    ]
    t_sum = Table(sum_data, colWidths=[130, 130, 130, 130])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_sum)
    elements.append(Spacer(1, 15))

    if logs_to_print:
        log_data = [["Time/Date", "Index", "Type", "Entry", "Exit", "PnL", "Status"]]
        for log in logs_to_print:
            log_data.append([
                log.get('time', log.get('date', '')), log['index'], log['type'],
                f"{log['entry']:.2f}", f"{log['exit']:.2f}",
                f"{log['pnl']:+.2f}", log['status']
            ])
        t_log = Table(log_data, colWidths=[70, 80, 50, 75, 75, 75, 125])
        t_log.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4A5568")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        elements.append(t_log)
    else:
        elements.append(Paragraph("<i>No trades recorded during this period.</i>", styles['Normal']))

    doc.build(elements)

# --- STARTUP SCANNER ALERT (09:00 AM) ---
send_telegram_alert(
    f"🚀 *NIFTY & BANK NIFTY SCANNER ACTIVATED*\n\n"
    f"⚡ Strategy: *{STRATEGY_DISPLAY_NAME}*\n"
    f"🕒 Trading Window: *09:30 AM - 03:20 PM IST*\n"
    f"🛡️ Protection: Strict SL + Early Cut + Reversal Lock\n"
    f"🎯 Target Engine: T1 (Trail to Cost), T2 (Trail to T1), T3\n"
    f"💵 Option Engine: Live Strike Buy & Sell Target/SL Levels Included\n"
    f"🔥 Features: 09:05 AM Pivots + 01:15 PM Hero-Zero + PDF Ledgers"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Live Fetch Note: {e}")
        return None

# --- MAIN EXECUTION ENGINE (09:00 AM - 03:40 PM) ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%H:%M:%S')

        # Schedules
        pivot_alert_time = datetime.strptime("09:05", "%H:%M").time()
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        # 1. 09:05 AM CAMARILLA PIVOTS ALERT (R1-R4 & S1-S4)
        if not pivots_alert_sent and current_time >= pivot_alert_time:
            pivots_alert_sent = True
            p_msg = f"📐 *DAILY CAMARILLA PIVOT LEVELS (09:05 AM IST)*\n\n"
            for idx in INDEX_WATCHLIST:
                lvl = camarilla_levels.get(idx)
                if lvl:
                    p_msg += (
                        f"🔹 *{idx}* (Prev Close: {lvl['Prev_Close']})\n"
                        f"• R4 (Breakout Buy): {lvl['R4']:.2f}\n"
                        f"• R3: {lvl['R3']:.2f} | R2: {lvl['R2']:.2f} | R1: {lvl['R1']:.2f}\n"
                        f"• S1: {lvl['S1']:.2f} | S2: {lvl['S2']:.2f} | S3: {lvl['S3']:.2f}\n"
                        f"• S4 (Breakdown Sell): {lvl['S4']:.2f}\n\n"
                    )
            send_telegram_alert(p_msg)

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 2. 03:40 PM DAILY CLOSING REPORT + DAILY & MONTHLY PDF
        if current_time >= shutdown_time:
            date_str = now.strftime('%d-%b-%Y')
            total = trade_stats['total_signals']
            wins = trade_stats['target_hits']
            win_rate = (wins / total * 100) if total > 0 else 0.0

            summary = (
                f"📊 *MARKET CLOSED (DAILY REPORT)*\n\n"
                f"⚡ Strategy: *{STRATEGY_DISPLAY_NAME}*\n"
                f"📅 Date: {date_str}\n\n"
                f"• Total Signals: {total}\n"
                f"• Targets / Locks: {wins}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n"
                f"• Early Cuts: {trade_stats['early_cuts']}\n"
                f"🏆 Win Rate: {win_rate:.1f}%\n\n"
                f"📄 Dispatching Daily PDF Report..."
            )
            send_telegram_alert(summary)

            # Daily PDF Dispatch
            pdf_daily = f"Daily_Report_{date_str}.pdf"
            generate_pdf_report(pdf_daily, "DAILY PERFORMANCE REPORT", date_str, trade_logs)
            send_telegram_document(pdf_daily, caption=f"📄 Daily Performance Report - {date_str}")
            send_email_with_pdf(pdf_daily, f"Daily Trading Report - {date_str}", summary)

            # Monthly Ledger Dispatch on Month End
            is_month_end = (now.day >= 28 and now.weekday() in [3, 4])
            if is_month_end and os.path.exists(MONTHLY_LEDGER_FILE):
                try:
                    with open(MONTHLY_LEDGER_FILE, 'r') as f:
                        monthly_logs = json.load(f)
                    month_str = now.strftime('%B-%Y')
                    pdf_monthly = f"Monthly_Ledger_{month_str}.pdf"
                    generate_pdf_report(pdf_monthly, f"MONTHLY PERFORMANCE LEDGER ({month_str})", month_str, monthly_logs)
                    send_telegram_document(pdf_monthly, caption=f"📊 Monthly Performance Ledger - {month_str}")
                    send_email_with_pdf(pdf_monthly, f"Monthly Performance Ledger - {month_str}", f"Attached Monthly Ledger for {month_str}")
                except Exception as ex:
                    print(f"Monthly Ledger Dispatch Error: {ex}")

            print("Daily market session finished. Bot exiting safely.")
            break

        raw_data = get_live_index_data()

        if raw_data is not None and not raw_data.empty:
            prices_dict = {}
            for index_name in INDEX_WATCHLIST:
                row = raw_data[raw_data['index'] == index_name]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[index_name] = current_price

                    if index_name not in prev_close_dict and 'previousClose' in row.columns:
                        prev_close_dict[index_name] = float(str(row['previousClose'].values[0]).replace(',', ''))

                    # 3. HERO-ZERO EXPIRY ALERT (01:15 PM IST on Tuesday/Thursday)
                    if not hero_zero_sent and current_time >= hero_zero_time and today_weekday in [1, 3]:
                        step = 50 if index_name == "NIFTY 50" else 100
                        atm_k = int(round(current_price / step) * step)
                        hz_msg = (
                            f"🔥 *HERO-ZERO EXPIRY SETUP (01:15 PM IST)*\n\n"
                            f"📍 Index: *{index_name}* (Spot: {current_price:.2f})\n"
                            f"🎯 *Focus Strikes (₹15 - ₹35 Low Premium Range):*\n"
                            f"• Call Option: *{atm_k + step} CE*\n"
                            f"• Put Option: *{atm_k - step} PE*\n\n"
                            f"⚡ Strategy: Target 2x-3x on Camarilla breakout!"
                        )
                        send_telegram_alert(hz_msg)
                        hero_zero_sent = True

                    # --- ACTIVE TRADE POSITION TRACKING ---
                    trade = active_trades[index_name]
                    if trade is not None:
                        # 03:20 PM INTRADAY AUTO-EXIT
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            entry_log = {
                                'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                'index': index_name, 'type': trade['type'],
                                'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Auto-Exit 03:20'
                            }
                            trade_logs.append(entry_log)
                            record_to_monthly_ledger(entry_log)

                            send_telegram_alert(
                                f"⏰ *AUTO EXIT (03:20 PM CLOSE)*\n\n"
                                f"⚡ Strategy: *{trade['strategy']}*\n"
                                f"📍 Index: *{index_name}*\n"
                                f"💵 Exit Spot: *{current_price:.2f}* | PnL: *{pnl:+.2f}*\n"
                                f"🔒 Status: All open intraday positions squared off."
                            )
                            active_trades[index_name] = None
                            save_backup_state(active_trades)
                            continue

                        # --- BUY TRADE TRACKING ---
                        if trade['type'] == 'BUY':
                            gain = current_price - trade['entry']
                            if gain > trade.get('max_gain', 0):
                                trade['max_gain'] = gain

                            # A. False Breakout Early Cut (Drops below R3)
                            if not trade.get('t1_hit') and current_price < trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                pnl = current_price - trade['entry']
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Early Cut (R3)'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"⚠️ *FALSE BREAKOUT EARLY EXIT*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | PnL: *{pnl:+.2f}*\n"
                                    f"🛡️ Reason: Dropped below R3. Exit option quickly!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # B. Reversal Profit Lock (+30 pt spike, drops to <=10 pts)
                            if trade.get('max_gain', 0) >= 30 and gain <= 10:
                                pnl = current_price - trade['entry']
                                trade_stats['target_hits'] += 1
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Reversal Profit Lock'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🔒 *REVERSAL PROFIT LOCKED*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | PnL: *{pnl:+.2f}*\n"
                                    f"🛡️ Reason: Reversal after +30 pt spike. Profit secured!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # C. Stop Loss Hit
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'SL Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🛑 *STOP LOSS HIT!*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | SL: *{trade['sl']:.2f}*\n"
                                    f"❌ Status: Trade Closed. Exit Call options."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # D. Target 1 (Trail SL to Entry)
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Spot: *{current_price:.2f}* | T1: *{trade['t1']:.2f}*\n"
                                    f"🛡️ Action: Book 50% Option Profit. Move SL to Entry!"
                                )
                                save_backup_state(active_trades)

                            # E. Target 2 (Trail SL to Target 1)
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Spot: *{current_price:.2f}* | T2: *{trade['t2']:.2f}*\n"
                                    f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                                )
                                save_backup_state(active_trades)

                            # F. Final Target 3
                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                pnl = current_price - trade['entry']
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Target 3 Done'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"📍 Index: *{index_name}* (BUY)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | T3: *{trade['t3']:.2f}*\n"
                                    f"🏆 Status: Full Option Profit Booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                        # --- SELL TRADE TRACKING ---
                        elif trade['type'] == 'SELL':
                            gain = trade['entry'] - current_price
                            if gain > trade.get('max_gain', 0):
                                trade['max_gain'] = gain

                            # A. False Breakdown Early Cut (Bounces above S3)
                            if not trade.get('t1_hit') and current_price > trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                pnl = trade['entry'] - current_price
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Early Cut (S3)'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"⚠️ *FALSE BREAKDOWN EARLY EXIT*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | PnL: *{pnl:+.2f}*\n"
                                    f"🛡️ Reason: Rebounded above S3. Exit put options!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # B. Reversal Profit Lock
                            if trade.get('max_gain', 0) >= 30 and gain <= 10:
                                pnl = trade['entry'] - current_price
                                trade_stats['target_hits'] += 1
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Reversal Profit Lock'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🔒 *REVERSAL PROFIT LOCKED*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | PnL: *{pnl:+.2f}*\n"
                                    f"🛡️ Reason: Reversal after +30 pt drop. Profit secured!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # C. Stop Loss Hit
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'SL Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🛑 *STOP LOSS HIT!*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | SL: *{trade['sl']:.2f}*\n"
                                    f"❌ Status: Trade Closed. Exit Put options."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # D. Target 1
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Spot: *{current_price:.2f}* | T1: *{trade['t1']:.2f}*\n"
                                    f"🛡️ Action: Book 50% Option Profit. Move SL to Entry!"
                                )
                                save_backup_state(active_trades)

                            # E. Target 2
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Spot: *{current_price:.2f}* | T2: *{trade['t2']:.2f}*\n"
                                    f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                                )
                                save_backup_state(active_trades)

                            # F. Final Target 3
                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                pnl = trade['entry'] - current_price
                                entry_log = {
                                    'time': current_time_str, 'date': now.strftime('%d-%b-%Y'),
                                    'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Target 3 Done'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"📍 Index: *{index_name}* (SELL)\n"
                                    f"💵 Exit Spot: *{current_price:.2f}* | T3: *{trade['t3']:.2f}*\n"
                                    f"🏆 Status: Full Option Profit Booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                    # --- ZERO-DELAY LIVE TICK BREAKOUT DETECTION ---
                    pivots = camarilla_levels.get(index_name)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        r4 = pivots['R4']
                        s4 = pivots['S4']
                        r3 = pivots['R3']
                        s3 = pivots['S3']

                        # BUY BREAKOUT (Crossing R4)
                        if current_price > r4:
                            sl = round(r3, 2)
                            risk = round(current_price - sl, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price - 25.0, 2)

                            t1 = round(current_price + (risk * 1.0), 2)
                            t2 = round(current_price + (risk * 1.5), 2)
                            t3 = round(current_price + (risk * 2.5), 2)

                            active_trades[index_name] = {
                                'strategy': STRATEGY_DISPLAY_NAME,
                                'type': 'BUY',
                                'entry': current_price,
                                'sl': sl,
                                't1': t1, 't2': t2, 't3': t3,
                                'cut_level': r3,
                                'max_gain': 0.0,
                                't1_hit': False, 't2_hit': False
                            }
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            opt = get_option_recommendations(index_name, current_price, "BUY", risk)
                            msg = (
                                f"🟢 *{index_name} BUY SIGNAL*\n\n"
                                f"⚡ Strategy: *{STRATEGY_DISPLAY_NAME}*\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: *{current_price:.2f}* | SL: *{sl:.2f}*\n\n"
                                f"🛒 *OPTION BUYERS (CALL)*:\n"
                                f"• Strike: *{opt['buyer_strike']}*\n"
                                f"• Entry Approx: *₹{opt['buyer_entry']:.1f}*\n"
                                f"• SL: *₹{opt['buyer_sl']:.1f}*\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                                f"🛡️ *OPTION SELLERS (PUT)*:\n"
                                f"• Sell ATM: *{opt['seller_strike']}* @ ₹{opt['seller_entry']:.1f} (SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f})\n"
                                f"• Safe OTM: *{opt['safe_seller_strike']}* @ ₹{opt['safe_seller_entry']:.1f}\n\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                            )
                            send_telegram_alert(msg)

                        # SELL BREAKDOWN (Crossing S4)
                        elif current_price < s4:
                            sl = round(s3, 2)
                            risk = round(sl - current_price, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price + 25.0, 2)

                            t1 = round(current_price - (risk * 1.0), 2)
                            t2 = round(current_price - (risk * 1.5), 2)
                            t3 = round(current_price - (risk * 2.5), 2)

                            active_trades[index_name] = {
                                'strategy': STRATEGY_DISPLAY_NAME,
                                'type': 'SELL',
                                'entry': current_price,
                                'sl': sl,
                                't1': t1, 't2': t2, 't3': t3,
                                'cut_level': s3,
                                'max_gain': 0.0,
                                't1_hit': False, 't2_hit': False
                            }
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            opt = get_option_recommendations(index_name, current_price, "SELL", risk)
                            msg = (
                                f"🔴 *{index_name} SELL SIGNAL*\n\n"
                                f"⚡ Strategy: *{STRATEGY_DISPLAY_NAME}*\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: *{current_price:.2f}* | SL: *{sl:.2f}*\n\n"
                                f"🛒 *OPTION BUYERS (PUT)*:\n"
                                f"• Strike: *{opt['buyer_strike']}*\n"
                                f"• Entry Approx: *₹{opt['buyer_entry']:.1f}*\n"
                                f"• SL: *₹{opt['buyer_sl']:.1f}*\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                                f"🛡️ *OPTION SELLERS (CALL)*:\n"
                                f"• Sell ATM: *{opt['seller_strike']}* @ ₹{opt['seller_entry']:.1f} (SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f})\n"
                                f"• Safe OTM: *{opt['safe_seller_strike']}* @ ₹{opt['safe_seller_entry']:.1f}\n\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                            )
                            send_telegram_alert(msg)

            # --- HOURLY STATUS ALERT (+/- POINTS & %) ---
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 *HOURLY STATUS ALERT*\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• *{idx}*: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        # 3 സെക്കൻഡ് ഫാസ്റ്റ് റിഫ്രഷ് (സീറോ ലാഗ്)
        time.sleep(3)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(3)
