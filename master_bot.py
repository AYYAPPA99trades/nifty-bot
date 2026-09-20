import os
import sys
import json
import calendar
import datetime
import pytz
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import smtplib
import ssl
from email.message import EmailMessage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# ----------------- CONFIGURATION -----------------
WATCHLIST = ["^NSEI"]  # Nifty Spot
STATE_FILE = "trade_state_pro.json"
IST = pytz.timezone("Asia/Kolkata")
TARGET_EMAIL = "shinossanthagoi@gmailcom" # നിങ്ങളുടെ ഇമെയിൽ ഐഡി ഇവിടെ നൽകി

# Telegram Multi-Bot
TELEGRAM_TARGETS = [
    {
        "name": "Bot 1",
        "token": os.getenv("TELEGRAM_BOT_TOKEN_1", "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_1", "6789591588")
    },
    {
        "name": "Bot 2",
        "token": os.getenv("TELEGRAM_BOT_TOKEN_2", "8941192045:AAELQ21ZiFKnHMMySyOoMue-hzMgS9ZjotQ"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_2", "8996427731")
    }
]

# ----------------- HELPERS -----------------

def send_telegram(text: str):
    """ബ്രോഡ്കാസ്റ്റ് ടെലിഗ്രാം മെസ്സേജ്"""
    for target in TELEGRAM_TARGETS:
        if not target["token"] or not target["chat_id"]: continue
        url = f"https://api.telegram.org/bot{target['token']}/sendMessage"
        payload = {"chat_id": target["chat_id"], "text": text, "parse_mode": "HTML"}
        try: requests.post(url, json=payload, timeout=10)
        except: pass

def send_telegram_file(filepath: str, caption: str):
    """PDF ഫയൽ ടെലിഗ്രാമിലേക്ക് അയക്കുന്നു"""
    for target in TELEGRAM_TARGETS:
        if not target["token"] or not target["chat_id"]: continue
        url = f"https://api.telegram.org/bot{target['token']}/sendDocument"
        try:
            with open(filepath, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': target["chat_id"], 'caption': caption, 'parse_mode': 'HTML'}
                requests.post(url, files=files, data=data, timeout=30)
        except: pass

def send_email_with_pdf(filepath: str, subject: str, body: str):
    """PDF അറ്റാച്ച്മെന്റോടെ ഇമെയിൽ അയക്കുന്നു (GitHub Secrets ആവശ്യമാണ്)"""
    SENDER_EMAIL = os.getenv("EMAIL_SENDER")
    SENDER_PASSWORD = os.getenv("EMAIL_PASSWORD") # 'upbb zfwx qmds qopr' ഫോർമാറ്റ്

    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("Email secrets missing. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = TARGET_EMAIL
    msg.set_content(body)

    try:
        with open(filepath, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(filepath)
            msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email sending failed: {e}")

# ----------------- STATE MANAGEMENT -----------------

def load_state():
    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "signals_count": 0,
        "active_trade": None,
        "current_expiry_backlog": [],
        "pre_market_done": False,
        "post_market_done": False,
        "expiry_report_done": False
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                if state.get("date") == today_str:
                    return state
                else:
                    # പുതിയാ ദിവസം: ആക്റ്റീവ് ട്രേഡ് ഇല്ലെങ്കിൽ കൗണ്ട് റീസെറ്റ് ചെയ്യുക
                    state["date"] = today_str
                    if not state.get("active_trade"):
                        state["signals_count"] = 0
                    state["pre_market_done"] = False
                    state["post_market_done"] = False
                    state["expiry_report_done"] = False
                    return state
        except: pass
    return default_state

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ----------------- INDICATORS -----------------

def calculate_atr(df: pd.DataFrame, period: int = 14):
    """ATR കണക്കാക്കുന്നു (Dynamic SL/Target-ന്)"""
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).sum() / 14
    return atr

def get_market_data():
    df_5m = yf.download("^NSEI", period="2d", interval="5m", progress=False)
    df_daily = yf.download("^NSEI", period="3mo", interval="1d", progress=False)
    
    # Handle MultiIndex
    if isinstance(df_5m.columns, pd.MultiIndex): df_5m.columns = df_5m.columns.get_level_values(0)
    if isinstance(df_daily.columns, pd.MultiIndex): df_daily.columns = df_daily.columns.get_level_values(0)
    
    return df_5m, df_daily

# ----------------- PDF REPORT GENERATION -----------------

def generate_expiry_pdf_report(state, prev_expiry, curr_expiry):
    """പ്രൊഫഷണൽ എക്‌സ്‌പെയറി റിപ്പോർട്ട് PDF നിർമ്മിക്കുന്നു"""
    report_date = curr_expiry.strftime("%d_%b_%Y")
    filename = f"Nifty_Expiry_Report_{report_date}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story = []

    # Title & Header
    story.append(Paragraph(f"Nifty Pro - Monthly Expiry Performance Report", styles['Title']))
    story.append(Spacer(1, 12))
    period_str = f"Period: {prev_expiry.strftime('%d %b %Y')} to {curr_expiry.strftime('%d %b %Y')}"
    story.append(Paragraph(period_str, styles['Heading2']))
    story.append(Spacer(1, 12))

    # Calculate P&L Stats
    backlog = state.get("current_expiry_backlog", [])
    df = pd.DataFrame(backlog)
    
    if df.empty:
        story.append(Paragraph("No trades executed in this expiry period.", styles['Normal']))
    else:
        total_trades = len(df)
        wins = len(df[df['exit_reason'].str.contains('TARGET', na=False)])
        losses = len(df[df['exit_reason'] == 'SL'])
        # ഏകദേശ പോയിന്റുകൾ
        df['pts'] = np.where(df['exit_reason'] == 'SL', -df['sl_dist'], 0)
        df['pts'] = np.where(df['exit_reason'] == 'TARGET 1', df['pts'] + df['t1_dist'], df['pts'])
        df['pts'] = np.where(df['exit_reason'] == 'TARGET 2', df['pts'] + df['t2_dist'], df['pts'])
        df['pts'] = np.where(df['exit_reason'] == 'TARGET 3', df['pts'] + df['t3_dist'], df['pts'])
        df['pts'] = np.where(df['exit_reason'] == 'TRAIL_EXIT', df['pts'] + df['pts_at_exit'], df['pts'])

        total_pts = df['pts'].sum()
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

        # Summary Table
        summary_data = [
            ["Total Trades", "Wins", "Losses", "Win Rate %", "Total Spot Points"],
            [str(total_trades), str(wins), str(losses), f"{win_rate:.1f}%", f"{total_pts:.1f}"]
        ]
        sum_table = Table(summary_data, colWidths=[100, 80, 80, 100, 120])
        sum_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        story.append(Paragraph("Summary", styles['Heading3']))
        story.append(sum_table)
        story.append(Spacer(1, 24))

        # Detailed Trade Log Table
        story.append(Paragraph("Detailed Trade Log", styles['Heading3']))
        table_data = [["Date", "Type", "Entry", "SL", "T1", "T2", "T3", "Exit Price", "Reason", "Points"]]
        
        for _, row in df.iterrows():
            pnl_color = colors.green if row['pts'] > 0 else colors.red if row['pts'] < 0 else colors.black
            table_data.append([
                row['date'], row['type'], f"{row['entry']:.1f}", f"{row['sl']:.1f}",
                f"{row['t1']:.1f}", f"{row['t2']:.1f}", f"{row['t3']:.1f}",
                f"{row['exit_price']:.1f}", row['exit_reason'], 
                Paragraph(f"<b>{row['pts']:.1f}</b>", styles['Normal'] if row['pts']>=0 else styles['Normal']) # Simplifying color logic for PDF table compatibility
            ])

        # Create the table
        trade_table = Table(table_data, headerRows=1, colWidths=[65, 55, 60, 50, 50, 50, 50, 60, 80, 50])
        ts = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ])
        
        # Row highlighting based on Profit/Loss
        for i in range(1, len(table_data)):
            pts_val = float(table_data[i][-1].text.strip('<b>')) if hasattr(table_data[i][-1], 'text') else float(table_data[i][-1])
            if pts_val > 0: ts.add('BACKGROUND', (9, i), (9, i), colors.lightgreen)
            elif pts_val < 0: ts.add('BACKGROUND', (9, i), (9, i), colors.lightcoral)

        trade_table.setStyle(ts)
        story.append(trade_table)

    # Build PDF
    try:
        doc.build(story)
        return filename
    except Exception as e:
        print(f"PDF generation failed: {e}")
        return None

# ----------------- CORE LOGIC -----------------

def manage_active_trade(df_5m, df_daily, state):
    """ലൈവ് ട്രേഡ് മാനേജ്മെന്റ് (Multiple Targets & Trailing)"""
    trade = state.get("active_trade")
    if not trade: return False

    ticker = trade["symbol"]
    curr_df = df_5m
    if curr_df.empty: return True

    curr = curr_df.iloc[-1]
    cmp = float(curr['Close'])
    entry = trade["entry"]
    trade_type = trade["type"]
    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")

    # Exit variables
    exit_triggered = False
    exit_price = cmp
    exit_reason = ""
    pts = 0

    # 1. STOP LOSS CHECK (T1 അടിച്ചിട്ടില്ലെങ്കിൽ മാത്രം)
    if not trade["t1_hit"] and not exit_triggered:
        if (trade_type == "CE" and cmp <= trade["sl"]) or (trade_type == "PE" and cmp >= trade["sl"]):
            exit_triggered = True
            exit_price = trade["sl"]
            exit_reason = "SL"
            pts = -trade["sl_dist"]
            send_telegram(f"🛑 <b>{ticker} {trade_type} - STOP LOSS HIT</b>\nExit @ {exit_price:.2f}")

    # 2. TARGET CHECK (T1, T2, T3)
    if not exit_triggered:
        # T1 (1:1 RRR) - ഇവിടെ SL Trail ചെയ്യുന്നു, പിന്നീട് SL Alert വരില്ല
        if not trade["t1_hit"]:
            if (trade_type == "CE" and cmp >= trade["t1"]) or (trade_type == "PE" and cmp <= trade["t1"]):
                trade["t1_hit"] = True
                trade["sl"] = entry # SL എൻട്രി പ്രൈസിലേക്ക് മാറ്റുന്നു (Trailing)
                trade["exit_reason_locked"] = "TARGET 1"
                send_telegram(f"🎯 <b>{ticker} {trade_type} - TARGET 1 Hit</b> ({cmp:.2f})\n🛡️ SL Trailed to Cost: {entry:.2f}\n(No more SL alerts for this trade)")
        
        # T2 (1:2 RRR) - ലൈവ് അലേർട്ട്
        if trade["t1_hit"] and not trade["t2_hit"]:
            if (trade_type == "CE" and cmp >= trade["t2"]) or (trade_type == "PE" and cmp <= trade["t2"]):
                trade["t2_hit"] = True
                trade["exit_reason_locked"] = "TARGET 2"
                send_telegram(f"🔥 <b>{ticker} {trade_type} - TARGET 2 Hit</b> ({cmp:.2f})\n(Holding for T3 or Trail Exit)")

        # T3 (1:3 RRR) - ലൈവ് അലേർട്ട് & Exit
        if trade["t2_hit"] and not trade["t3_hit"]:
            if (trade_type == "CE" and cmp >= trade["t3"]) or (trade_type == "PE" and cmp <= trade["t3"]):
                trade["t3_hit"] = True
                exit_triggered = True
                exit_price = trade["t3"]
                exit_reason = "TARGET 3"
                pts = trade["t3_dist"]
                send_telegram(f"🏆 <b>{ticker} {trade_type} - TARGET 3 Hit - FULL EXIT</b>\nExit @ {exit_price:.2f}")

    # 3. TRAILING EXIT CHECK (T1-ന് ശേഷം വില വീണ്ടും കോസ്റ്റിലേക്ക് വന്നാൽ)
    if trade["t1_hit"] and not exit_triggered:
        if (trade_type == "CE" and cmp <= entry) or (trade_type == "PE" and cmp >= entry):
            exit_triggered = True
            exit_price = entry
            # T2 അടിച്ച ശേഷമാണോ കോസ്റ്റിൽ വന്നത് എന്ന് നോക്കുന്നു
            exit_reason = "TRAIL_EXIT (T2 Done)" if trade["t2_hit"] else "TRAIL_EXIT (Cost)"
            pts = trade["pts_at_exit"] if trade["pts_at_exit"] > 0 else 0 # T1, T2 പ്രോഫിറ്റ് ഉറപ്പാക്കുന്നു (Simplification: Spot points tracking is complex, we assume exit at T1 or cost here)
            # Simplification: Assume if T1 hit and then cmp reverts to entry, profit is T1 dist.
            pts = trade["t1_dist"] if not trade["t2_hit"] else trade["t2_dist"] # This is an approximation
            send_telegram(f"🛡️ <b>{ticker} {trade_type} - Trailing Exit</b>\nClosed @ Cost ({exit_price:.2f})\nFinal Reason: {exit_reason}")

    # EOD SQUARE OFF (3:15 PM)
    now_ist = datetime.datetime.now(IST).time()
    if not exit_triggered and now_ist >= datetime.time(15, 15):
        exit_triggered = True
        exit_price = cmp
        pts = cmp - entry if trade_type == "CE" else entry - cmp
        final_r = trade.get("exit_reason_locked", "EOD EXIT")
        exit_reason = f"EOD ({final_r})"
        send_telegram(f"🕒 <b>{ticker} {trade_type} - Market Closing Exit</b>\nExit @ {exit_price:.2f}")

    # If trade completed, save to backlog
    if exit_triggered:
        trade_log = {
            "date": today_str,
            "symbol": ticker,
            "type": trade_type,
            "entry": entry,
            "sl": trade["sl_original"],
            "t1": trade["t1"],
            "t2": trade["t2"],
            "t3": trade["t3"],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "sl_dist": trade["sl_dist"],
            "t1_dist": trade["t1_dist"],
            "t2_dist": trade["t2_dist"],
            "t3_dist": trade["t3_dist"],
            "pts_at_exit": pts
        }
        state["current_expiry_backlog"].append(trade_log)
        state["active_trade"] = None
        save_state(state)
        return False # No longer active
    else:
        # Save state with updated hits
        state["active_trade"] = trade
        save_state(state)
        return True # Still active

def scan_for_entries(df_5m, df_daily, state):
    """ATR അടിസ്ഥാനമാക്കി Dynamic SL/Target നിശ്ചയിച്ച് സിഗ്നൽ നൽകുന്നു"""
    # ... (ORB conditions same as original code, using ATR for SL/Target)
    # This part is simplified to focus on dynamic calculation
    
    ticker = "^NSEI"
    curr_df = df_5m
    if curr_df.empty: return

    # Calculate ATR on daily data for SL/Target
    atr = calculate_atr(df_daily).iloc[-1]
    
    # Example Conditions (Replace with original ORB logic)
    # Here using placeholder logic to generate a dynamic signal for demonstration
    curr = curr_df.iloc[-1]
    close = float(curr['Close'])
    
    # Placeholder: Signal if count < max
    if state["signals_count"] < 3 and not state["active_trade"]:
        
        # dynamic distances
        # SL = 1 * ATR (Daily ATR), T1=1:1, T2=1:2, T3=1:3
        # Assuming ATR is approx 150-200, SL will be around 150-200 pts spot.
        # If this is too wide for intraday, you can use ATR/3 or ATR/4.
        # Let's use ATR / 3 for a tighter intraday setup, e.g., 60-70 pts.
        
        sl_dist = round(atr / 3, 1)
        
        # Placeholder Type
        trade_type = "CE" # Example
        entry_price = close
        sl = entry_price - sl_dist
        t1 = entry_price + sl_dist
        t2 = entry_price + (sl_dist * 2)
        t3 = entry_price + (sl_dist * 3)

        new_trade = {
            "symbol": ticker,
            "type": trade_type,
            "entry": entry_price,
            "sl_original": sl,
            "sl": sl,
            "t1": t1,
            "t2": t2,
            "t3": t3,
            "sl_dist": sl_dist,
            "t1_dist": sl_dist,
            "t2_dist": sl_dist * 2,
            "t3_dist": sl_dist * 3,
            "t1_hit": False,
            "t2_hit": False,
            "t3_hit": False,
            "pts_at_exit": 0, # Placeholder
            "exit_reason_locked": ""
        }
        
        msg = (
            f"🚀 <b>NIFTY Dynamic Signal ({trade_type})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Spot Entry: <b>{entry_price:.2f}</b>\n"
            f"🛑 SL: {sl:.2f} (ATR Based: {sl_dist})\n"
            f"🎯 T1 (1:RR): <b>{t1:.2f}</b> (Trail to Cost)\n"
            f"🎯 T2 (2:RR): <b>{t2:.2f}</b>\n"
            f"🏆 T3 (3:RR): <b>{t3:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>T1 അടിച്ചാൽ SL കോസ്റ്റിലേക്ക് ട്രെയിൽ ചെയ്യപ്പെടും. പിന്നീട് SL അലേർട്ട് വരില്ല. T2, T3 എന്നിവ ലൈവ് ആയി ട്രാക്ക് ചെയ്യും.</i>"
        )
        send_telegram(msg)
        state["active_trade"] = new_trade
        state["signals_count"] += 1
        save_state(state)

# ----------------- EXPIRY HANDLING -----------------

def check_and_run_expiry_report(df_daily, state):
    trading_days = [d.date() for d in df_daily.index]
    today_date = datetime.datetime.now(IST).date()
    curr_year, curr_month = today_date.year, today_date.month

    # Current month target expiry
    this_month_target = get_target_expiry_weekday(curr_year, curr_month, 3)
    current_expiry_date = get_actual_expiry_date(this_month_target, trading_days)

    if today_date != current_expiry_date:
        return

    # If today is expiry and report not done, generate it
    # Find Previous Expiry
    if curr_month == 1: prev_m, prev_y = 12, curr_year - 1
    else: prev_m, prev_y = curr_month - 1, curr_year
    prev_month_target = get_target_expiry_weekday(prev_y, prev_m, 3)
    prev_expiry_date = get_actual_expiry_date(prev_month_target, trading_days)

    print(f"Generating Expiry Report for {prev_expiry_date} - {current_expiry_date}")
    send_telegram(f"📋 <b>Monthly Expiry Report</b>\nGenerating professional P&L PDF report...")

    # 1. Generate PDF
    pdf_path = generate_expiry_pdf_report(state, prev_expiry_date, current_expiry_date)

    if pdf_path and os.path.exists(pdf_path):
        # 2. Send via Telegram
        send_telegram_file(pdf_path, f"📄 Nifty Pro Professional Expiry Report ({prev_expiry_date} - {current_expiry_date})")
        
        # 3. Send via Email
        email_subj = f"Nifty Pro - Professional Expiry P&L Report - {current_expiry_date}"
        email_body = (
            f"Hello,\n\n"
            f"Please find attached the professional P&L report for Nifty Pro trading bot.\n"
            f"Period: {prev_expiry_date} to {current_expiry_date} (Expiry to Expiry).\n\n"
            f"Regards,\nNifty Pro Bot"
        )
        send_email_with_pdf(pdf_path, email_subj, email_body)
        
        # 4. Clean up Backlog & State
        state["current_expiry_backlog"] = []
        state["expiry_report_done"] = True
        save_state(state)
        try: os.remove(pdf_path) # Remove local file after sending
        except: pass
    else:
        send_telegram("⚠️ PDF Generation failed. Report sending aborted.")

# ----------------- MAIN -----------------

def main():
    state = load_state()
    df_5m, df_daily = get_market_data()
    now_ist = datetime.datetime.now(IST).time()

    # 0. Active Trade Management (Primary priority)
    is_active = manage_active_trade(df_5m, df_daily, state)

    # 1. Signal Scanning (if no active trade)
    if not is_active and datetime.time(9, 30) <= now_ist <= datetime.time(15, 00):
        scan_for_entries(df_5m, df_daily, state)

    # 2. Expiry Report (3:45 PM)
    if not state.get("expiry_report_done") and now_ist >= datetime.time(15, 45):
        check_and_run_expiry_report(df_daily, state)

    # 3. Post-Market daily clean up (not needed with structure)
    save_state(state)

if __name__ == "__main__":
    # Test Alert
    # send_telegram("🔔 <b>Nifty Pro Pro-Management Update</b>: Dynamic SL/Target & PDF Reports initialized.")
    main()
