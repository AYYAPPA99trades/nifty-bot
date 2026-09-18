import os
import time
import datetime
import threading
import sqlite3
import requests
import holidays
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from flask import Flask
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# -------------------------------------------------------------
# 1. FLASK WEB SERVER (Render സൗജന്യമായി ഉറങ്ങിപ്പോകാതിരിക്കാൻ)
# -------------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Nifty Trading Bot is Running Live 24x7 on Render!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# വെബ് സെർവർ ബാക്ക്ഗ്രൗണ്ടിൽ സ്റ്റാർട്ട് ചെയ്യുന്നു
threading.Thread(target=run_web_server, daemon=True).start()

# -------------------------------------------------------------
# 2. BOT CONFIGURATION & BACKUP DATABASE
# -------------------------------------------------------------
BOTS = [
    {
        "token": os.getenv("BOT1_TOKEN", "8941192045:AAELQ21ZiFKnHMMySyOoMue-hzMgS9ZjotQ"),[span_0](start_span)[span_0](end_span)
        "chat_id": os.getenv("CHANNEL_ID_1")
    },
    {
        "token": os.getenv("BOT2_TOKEN", "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0"),[span_1](start_span)[span_1](end_span)
        "chat_id": os.getenv("CHANNEL_ID_2")
    }
]

# ബോട്ട് റീസ്റ്റാർട്ട് ആയാലും ഡാറ്റ നഷ്ടപ്പെടാതിരിക്കാനുള്ള SQLite ബാക്കപ്പ്
conn = sqlite3.connect("trading_backup.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS trades 
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT, type TEXT, strike TEXT,
                   entry REAL, sl REAL, t1 REAL, t2 REAL, t3 REAL, 
                   t1_hit INT, t2_hit INT, t3_hit INT, is_closed INT, close_reason TEXT)''')
conn.commit()

def send_alert(message):
    for b in BOTS:
        if b["token"] and b["chat_id"]:
            url = f"https://api.telegram.org/bot{b['token']}/sendMessage"
            payload = {"chat_id": b["chat_id"], "text": message, "parse_mode": "Markdown"}
            try:
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                print(f"Telegram Alert Error: {e}")

def send_telegram_file(file_path, caption):
    for b in BOTS:
        if b["token"] and b["chat_id"]:
            url = f"https://api.telegram.org/bot{b['token']}/sendDocument"
            try:
                with open(file_path, 'rb') as doc:
                    requests.post(url, data={'chat_id': b['chat_id'], 'caption': caption}, files={'document': doc}, timeout=20)
            except Exception as e:
                print(f"Telegram File Send Error: {e}")

# -------------------------------------------------------------
# 3. DYNAMIC EXPIRY & MORNING PIVOTS
# -------------------------------------------------------------
def get_current_expiry():
    today = datetime.date.today()
    # Nifty വ്യാഴാഴ്ച എക്സ്പയറി കണ്ടെത്തുന്നു
    thursday = today + datetime.timedelta((3 - today.weekday()) % 7)
    india_holidays = holidays.India()
    while thursday in india_holidays:
        thursday -= datetime.timedelta(days=1)
    return thursday.strftime('%d-%b-%Y')

def send_morning_pivots():
    df = yf.download("^NSEI", period="2d", interval="1d", progress=False)
    if len(df) >= 2:
        prev = df.iloc[-2]
        h, l, c = float(prev['High']), float(prev['Low']), float(prev['Close'])
        
        p = (h + l + c) / 3
        r1, s1 = (2 * p) - l, (2 * p) - h
        r2, s2 = p + (h - l), p - (h - l)
        r3, s3 = h + 2 * (p - l), l - 2 * (h - p)
        r4, s4 = h + 3 * (p - l), l - 3 * (h - p)

        msg = (
            f"🌅 *NIFTY 50 DAILY PIVOTS (9:10 AM)*\n"
            f"📅 Date: `{datetime.date.today()}` | Expiry: `{get_current_expiry()}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔴 *Resistance Levels:*\n"
            f"• R4: `{r4:.1f}` | R3: `{r3:.1f}`\n"
            f"• R2: `{r2:.1f}` | R1: `{r1:.1f}`\n\n"
            f"⚪ *Central Pivot:* `{p:.1f}`\n\n"
            f"🟢 *Support Levels:*\n"
            f"• S1: `{s1:.1f}` | S2: `{s2:.1f}`\n"
            f"• S3: `{s3:.1f}` | S4: `{s4:.1f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n🎯 Trade with discipline!"
        )
        send_alert(msg)

def get_atm_strike(price, trade_type):
    rounded = round(price / 50) * 50
    if trade_type == "BUY_CE":
        buyer = f"{rounded} CE"
        seller = f"{rounded + 150} PE"
    else:
        buyer = f"{rounded} PE"
        seller = f"{rounded - 150} CE"
    return buyer, seller

# -------------------------------------------------------------
# 4. SIGNAL GENERATION & LIVE TARGET/SL ENGINE
# -------------------------------------------------------------
def check_signals():
    df = yf.download("^NSEI", period="2d", interval="5m", progress=False)
    if df.empty or len(df) < 50:
        return

    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['VWAP'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    df['ADX'] = adx_df['ADX_14']
    st_df = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=2.0)
    df['ST_DIR'] = st_df['SUPERTd_10_2.0']

    curr = df.iloc[-2]
    prev = df.iloc[-3]

    close = float(curr['Close'])
    atr = float(curr['ATR'])
    adx = float(curr['ADX'])

    # നിലവിൽ ഓപ്പൺ പൊസിഷൻ ഉണ്ടെങ്കിൽ അത് ട്രാക്ക് ചെയ്യുക
    cursor.execute("SELECT id FROM trades WHERE is_closed = 0")
    if cursor.fetchone():
        track_open_trades(close)
        return

    bullish_flip = (prev['ST_DIR'] == -1) and (curr['ST_DIR'] == 1)
    bearish_flip = (prev['ST_DIR'] == 1) and (curr['ST_DIR'] == -1)
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    # BUY CALL എൻട്രി
    if bullish_flip and (close > float(curr['EMA200'])) and (close > float(curr['VWAP'])) and (adx > 22):
        sl = round(close - (1.0 * atr), 1)
        t1 = round(close + (1.2 * atr), 1)
        t2 = round(close + (2.4 * atr), 1)
        t3 = round(close + (3.6 * atr), 1)
        buyer_opt, seller_opt = get_atm_strike(close, "BUY_CE")

        cursor.execute('''INSERT INTO trades (time, symbol, type, strike, entry, sl, t1, t2, t3, t1_hit, t2_hit, t3_hit, is_closed) 
                          VALUES (?, 'NIFTY', 'BUY_CE', ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)''',
                       (now_str, buyer_opt, close, sl, t1, t2, t3))
        conn.commit()

        msg = (
            f"🟢 *NEW SIGNAL: NIFTY BUY CE* 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Time: `{now_str}`\n"
            f"⚡ *Spot Entry:* `{close:.1f}`\n"
            f"🎯 *Option Buyer Strike:* `{buyer_opt}`\n"
            f"🛡 *Option Seller Strike:* `{seller_opt}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *T1:* `{t1}` (+{round(1.2*atr,1)} pts)\n"
            f"🎯 *T2:* `{t2}` (+{round(2.4*atr,1)} pts)\n"
            f"🎯 *T3:* `{t3}` (+{round(3.6*atr,1)} pts)\n"
            f"🛑 *Initial SL:* `{sl}` (-{round(1.0*atr,1)} pts)\n"
            f"📊 ADX: `{adx:.1f}` | ATR: `{atr:.1f}`"
        )
        send_alert(msg)

    # BUY PUT എൻട്രി
    elif bearish_flip and (close < float(curr['EMA200'])) and (close < float(curr['VWAP'])) and (adx > 22):
        sl = round(close + (1.0 * atr), 1)
        t1 = round(close - (1.2 * atr), 1)
        t2 = round(close - (2.4 * atr), 1)
        t3 = round(close - (3.6 * atr), 1)
        buyer_opt, seller_opt = get_atm_strike(close, "BUY_PE")

        cursor.execute('''INSERT INTO trades (time, symbol, type, strike, entry, sl, t1, t2, t3, t1_hit, t2_hit, t3_hit, is_closed) 
                          VALUES (?, 'NIFTY', 'BUY_PE', ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)''',
                       (now_str, buyer_opt, close, sl, t1, t2, t3))
        conn.commit()

        msg = (
            f"🔴 *NEW SIGNAL: NIFTY BUY PE* 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Time: `{now_str}`\n"
            f"⚡ *Spot Entry:* `{close:.1f}`\n"
            f"🎯 *Option Buyer Strike:* `{buyer_opt}`\n"
            f"🛡 *Option Seller Strike:* `{seller_opt}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *T1:* `{t1}` (-{round(1.2*atr,1)} pts)\n"
            f"🎯 *T2:* `{t2}` (-{round(2.4*atr,1)} pts)\n"
            f"🎯 *T3:* `{t3}` (-{round(3.6*atr,1)} pts)\n"
            f"🛑 *Initial SL:* `{sl}` (+{round(1.0*atr,1)} pts)\n"
            f"📊 ADX: `{adx:.1f}` | ATR: `{atr:.1f}`"
        )
        send_alert(msg)

def track_open_trades(price):
    cursor.execute("SELECT id, symbol, type, strike, entry, sl, t1, t2, t3, t1_hit, t2_hit, t3_hit FROM trades WHERE is_closed = 0")
    row = cursor.fetchone()
    if not row:
        return

    t_id, sym, t_type, strike, entry, sl, t1, t2, t3, t1_hit, t2_hit, t3_hit = row

    if t_type == "BUY_CE":
        # T1 Hit
        if not t1_hit and price >= t1:
            cursor.execute("UPDATE trades SET t1_hit = 1 WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🎯 *TARGET 1 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t1}` crossed! SL cancelled (Trail to Cost).")

        # T2 Hit (T1 അടിച്ച ശേഷം മാത്രം)
        if t1_hit and not t2_hit and price >= t2:
            cursor.execute("UPDATE trades SET t2_hit = 1 WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🚀 *TARGET 2 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t2}` crossed! Locking maximum profits.")

        # T3 Hit
        if t2_hit and not t3_hit and price >= t3:
            cursor.execute("UPDATE trades SET t3_hit = 1, is_closed = 1, close_reason = 'T3_HIT' WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🔥 *FINAL TARGET 3 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t3}` reached! Full Profit Booked.")

        # Stop Loss (T1 അടിക്കുന്നതിന് മുൻപ് മാത്രം പരിശോധിക്കുന്നു)
        if not t1_hit and price <= sl:
            cursor.execute("UPDATE trades SET is_closed = 1, close_reason = 'SL_HIT' WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🛑 *STOP LOSS HIT* 🔴\nStrike: `{strike}`\nLevel `{sl}` hit. Position Closed.")

    elif t_type == "BUY_PE":
        if not t1_hit and price <= t1:
            cursor.execute("UPDATE trades SET t1_hit = 1 WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🎯 *TARGET 1 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t1}` crossed! SL cancelled (Trail to Cost).")

        if t1_hit and not t2_hit and price <= t2:
            cursor.execute("UPDATE trades SET t2_hit = 1 WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🚀 *TARGET 2 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t2}` crossed! Locking maximum profits.")

        if t2_hit and not t3_hit and price <= t3:
            cursor.execute("UPDATE trades SET t3_hit = 1, is_closed = 1, close_reason = 'T3_HIT' WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🔥 *FINAL TARGET 3 HIT!* 🟢\nStrike: `{strike}`\nLevel `{t3}` reached! Full Profit Booked.")

        if not t1_hit and price >= sl:
            cursor.execute("UPDATE trades SET is_closed = 1, close_reason = 'SL_HIT' WHERE id = ?", (t_id,))
            conn.commit()
            send_alert(f"🛑 *STOP LOSS HIT* 🔴\nStrike: `{strike}`\nLevel `{sl}` hit. Position Closed.")

# -------------------------------------------------------------
# 5. CLOSING ALERTS & PDF PERFORMANCE REPORT
# -------------------------------------------------------------
def market_close_squareoff():
    cursor.execute("UPDATE trades SET is_closed = 1, close_reason = '3:15_EXIT' WHERE is_closed = 0")
    conn.commit()
    send_alert("⚠️ *3:15 PM INTRADAY AUTO-EXIT ALERT* ⚠️\n━━━━━━━━━━━━━━━━━━━━\nAll open intraday positions should be closed now to avoid broker auto-square-off charges.")

def generate_daily_report():
    pdf_filename = f"Trade_Report_{datetime.date.today()}.pdf"
    c = canvas.Canvas(pdf_filename, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(180, 750, "DAILY NIFTY TRADING REPORT")
    c.setFont("Helvetica", 11)
    c.drawString(50, 720, f"Date: {datetime.date.today()} | Expiry: {get_current_expiry()}")
    c.line(50, 710, 550, 710)

    cursor.execute("SELECT time, symbol, type, strike, entry, is_closed, close_reason FROM trades")
    trades = cursor.fetchall()
    
    y = 680
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Time | Symbol | Strike | Type | Entry | Status")
    y -= 20
    c.setFont("Helvetica", 9)

    for t in trades:
        line = f"{t[0]} | {t[1]} | {t[3]} | {t[2]} | {t[4]} | {t[6] or 'OPEN'}"
        c.drawString(50, y, line)
        y -= 18

    c.save()
    send_telegram_file(pdf_filename, "📊 *Daily Performance PDF Report Generated.*")

# -------------------------------------------------------------
# 6. CONTINUOUS MONITORING LOOP (9:00 AM - 3:40 PM)
# -------------------------------------------------------------
def main():
    send_alert("🤖 *Nifty Trading Bot Started Successfully on Render.*")
    pivots_sent = False
    squareoff_sent = False
    report_sent = False

    while True:
        now = datetime.datetime.now().time()
        
        # 9:10 AM - Morning Pivots
        if now.hour == 9 and now.minute == 10 and not pivots_sent:
            send_morning_pivots()
            pivots_sent = True

        # 9:15 AM to 3:30 PM - Live Data & Signals
        if datetime.time(9, 15) <= now <= datetime.time(3, 30):
            try:
                check_signals()
            except Exception as e:
                print(f"Loop Execution Error: {e}")

        # 3:15 PM - Intraday Auto-Squareoff Alert
        if now.hour == 15 and now.minute == 15 and not squareoff_sent:
            market_close_squareoff()
            squareoff_sent = True

        # 3:40 PM - Daily PDF Summary
        if now.hour == 15 and now.minute == 40 and not report_sent:
            generate_daily_report()
            report_sent = True

        time.sleep(10)  # ഓരോ 10 സെക്കൻഡിലും ലൈവായി പരിശോധിക്കുന്നു

if __name__ == "__main__":
    main()
