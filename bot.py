import time
import requests
import datetime
import pytz
import traceback
import yfinance as yf
import pandas_ta as ta

TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]

IST = pytz.timezone('Asia/Kolkata')

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
    "t3_hit": False,
    "exit_alert_sent": False
}

daily_alert_sent = False

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            print(f"Telegram Delivery Error for {chat_id}: {e}")

def run_strategy(symbol="^NSEI"):
    global trade_state, daily_alert_sent
    now = datetime.datetime.now(IST)
    current_time = now.time()

    # ശനി, ഞായർ ദിവസങ്ങളിൽ പ്രവർത്തനം ഒഴിവാക്കുന്നു
    if now.weekday() > 4:
        return

    # രാവിലെ 9:15-ന് ബോട്ട് ആക്ടീവ് ആണെന്നുള്ള ഡെയ്‌ലി അലർട്ട്
    if datetime.time(9, 15) <= current_time < datetime.time(9, 20):
        if not daily_alert_sent:
            send_telegram("🟢 *Market Opened (9:15 AM)*\nNIFTY 50 ബോട്ട് സജീവമായി മാർക്കറ്റ് നിരീക്ഷിക്കുന്നുണ്ട്.")
            daily_alert_sent = True
    elif current_time >= datetime.time(9, 25):
        daily_alert_sent = False

    # 3:15 PM ഇൻട്രാഡേ ഓട്ടോ-എക്സിറ്റ്
    if current_time >= datetime.time(15, 15) and trade_state["in_trade"] and not trade_state["exit_alert_sent"]:
        send_telegram(f"⏰ *INTRADAY AUTO-EXIT ALERT (3:15 PM)*\n\nAsset: NIFTY 50\nമാർക്കറ്റ് ക്ലോസ് ആകാൻ പോകുന്നു. എല്ലാ പൊസിഷനുകളും ക്ലോസ് ചെയ്യുക!")
        trade_state["exit_alert_sent"] = True
        trade_state["in_trade"] = False
        return

    if current_time >= datetime.time(15, 30):
        trade_state["in_trade"] = False
        trade_state["exit_alert_sent"] = False
        return

    # ട്രേഡിംഗ് സമയം: 9:15 AM മുതൽ 3:30 PM വരെ മാത്രം
    if current_time < datetime.time(9, 15) or current_time > datetime.time(15, 30):
        return

    # ഡാറ്റ ഡൗൺലോഡ്
    try:
        df = yf.download(tickers=symbol, period="1mo", interval="5m", progress=False)
    except Exception as err:
        send_telegram(f"⚠️ *Data Download Warning*\nമാർക്കറ്റ് ഡാറ്റ ലഭിക്കുന്നതിൽ തടസ്സം നേരിട്ടു: {err}")
        return

    if df.empty or len(df) < 50:
        return

    try:
        df['EMA_9'] = ta.ema(df['Close'], length=9)
        df['EMA_21'] = ta.ema(df['Close'], length=21)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['VWAP'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
    except Exception as calc_err:
        send_telegram(f"⚠️ *Indicator Calculation Error*\nഇൻഡിക്കേറ്റർ കണക്കാക്കുന്നതിൽ പ്രശ്നം: {calc_err}")
        return

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    close = round(float(curr['Close']), 2)
    high = round(float(curr['High']), 2)
    low = round(float(curr['Low']), 2)
    atr = round(float(curr['ATR']), 2)
    vwap = float(curr['VWAP']) if 'VWAP' in curr and not df['VWAP'].isna().all() else close
    rsi = float(curr['RSI'])
    ema9_curr, ema21_curr = float(curr['EMA_9']), float(curr['EMA_21'])
    ema9_prev, ema21_prev = float(prev['EMA_9']), float(prev['EMA_21'])

    # ടാർഗെറ്റും SL-ഉം മോണിറ്റർ ചെയ്യുന്നു
    if trade_state["in_trade"]:
        if trade_state["type"] == "BUY":
            if low <= trade_state["sl"]:
                send_telegram(f"❌ *STOP LOSS HIT (BUY EXIT)*\n\nAsset: NIFTY 50\nPrice: {trade_state['sl']}\nനഷ്ടം ഒഴിവാക്കാൻ എക്സിറ്റ് ചെയ്യുക.")
                trade_state["in_trade"] = False
            elif high >= trade_state["t1"] and not trade_state["t1_hit"]:
                send_telegram(f"🎯 *TARGET 1 ACHIEVED!*\n\nAsset: NIFTY 50\nT1 Price: {trade_state['t1']}\nഭാഗിക ലാഭം ബുക്ക് ചെയ്യുക!")
                trade_state["t1_hit"] = True
            elif high >= trade_state["t2"] and not trade_state["t2_hit"]:
                send_telegram(f"🎯🎯 *TARGET 2 ACHIEVED!*\n\nAsset: NIFTY 50\nT2 Price: {trade_state['t2']}\nStop Loss എൻട്രിയിലേക്ക് മാറ്റുക (Trail SL)!")
                trade_state["t2_hit"] = True
            elif high >= trade_state["t3"] and not trade_state["t3_hit"]:
                send_telegram(f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\nAsset: NIFTY 50\nT3 Price: {trade_state['t3']}\nപൂർണ്ണ ലാഭം എടുത്ത് എക്സിറ്റ് ചെയ്യുക!")
                trade_state["t3_hit"] = True
                trade_state["in_trade"] = False

        elif trade_state["type"] == "SELL":
            if high >= trade_state["sl"]:
                send_telegram(f"❌ *STOP LOSS HIT (SELL EXIT)*\n\nAsset: NIFTY 50\nPrice: {trade_state['sl']}\nഎക്സിറ്റ് ചെയ്യുക.")
                trade_state["in_trade"] = False
            elif low <= trade_state["t1"] and not trade_state["t1_hit"]:
                send_telegram(f"🎯 *TARGET 1 ACHIEVED!*\n\nAsset: NIFTY 50\nT1 Price: {trade_state['t1']}\nഭാഗിക ലാഭം ബുക്ക് ചെയ്യുക!")
                trade_state["t1_hit"] = True
            elif low <= trade_state["t2"] and not trade_state["t2_hit"]:
                send_telegram(f"🎯🎯 *TARGET 2 ACHIEVED!*\n\nAsset: NIFTY 50\nT2 Price: {trade_state['t2']}\nTrail SL!")
                trade_state["t2_hit"] = True
            elif low <= trade_state["t3"] and not trade_state["t3_hit"]:
                send_telegram(f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\nAsset: NIFTY 50\nT3 Price: {trade_state['t3']}\nപൂർണ്ണ ലാഭം എടുത്ത് എക്സിറ്റ് ചെയ്യുക!")
                trade_state["t3_hit"] = True
                trade_state["in_trade"] = False

    # പുതിയ എൻട്രികൾ
    else:
        if (ema9_prev <= ema21_prev and ema9_curr > ema21_curr) and (close >= vwap) and (rsi > 50):
            risk = atr * 1.5
            sl = round(close - risk, 2)
            t1 = round(close + (risk * 1.0), 2)
            t2 = round(close + (risk * 1.5), 2)
            t3 = round(close + (risk * 2.0), 2)

            trade_state.update({
                "in_trade": True, "type": "BUY", "entry": close, "sl": sl,
                "t1": t1, "t2": t2, "t3": t3, "t1_hit": False, "t2_hit": False, "t3_hit": False
            })

            msg = (
                f"🟢 *NIFTY 50 BUY SIGNAL*\n\n"
                f"💵 *Entry:* {close}\n"
                f"🛑 *Stop Loss:* {sl}\n\n"
                f"🎯 *Target 1:* {t1}\n"
                f"🎯 *Target 2:* {t2}\n"
                f"🎯 *Target 3:* {t3}"
            )
            send_telegram(msg)

        elif (ema9_prev >= ema21_prev and ema9_curr < ema21_curr) and (close <= vwap) and (rsi < 50):
            risk = atr * 1.5
            sl = round(close + risk, 2)
            t1 = round(close - (risk * 1.0), 2)
            t2 = round(close - (risk * 1.5), 2)
            t3 = round(close - (risk * 2.0), 2)

            trade_state.update({
                "in_trade": True, "type": "SELL", "entry": close, "sl": sl,
                "t1": t1, "t2": t2, "t3": t3, "t1_hit": False, "t2_hit": False, "t3_hit": False
            })

            msg = (
                f"🔴 *NIFTY 50 SELL SIGNAL*\n\n"
                f"💵 *Entry:* {close}\n"
                f"🛑 *Stop Loss:* {sl}\n\n"
                f"🎯 *Target 1:* {t1}\n"
                f"🎯 *Target 2:* {t2}\n"
                f"🎯 *Target 3:* {t3}"
            )
            send_telegram(msg)

# പ്രോഗ്രാം ആരംഭിക്കുന്നു
try:
    print("Starting NIFTY Trading Bot...")
    send_telegram("🚀 *NIFTY 50 Trading Bot Live!*\nഎല്ലാ സുരക്ഷാ അലർട്ടുകളോടും കൂടി ബോട്ട് പ്രവർത്തിക്കാൻ സജ്ജമായി.")

    while True:
        try:
            run_strategy("^NSEI")
        except Exception as loop_err:
            print(f"Loop error: {loop_err}")
            send_telegram(f"⚠️ *Strategy Loop Error*\nപ്രശ്നം: {loop_err}")
        time.sleep(60)

except Exception as fatal_crash:
    # ബോട്ട് അപ്രതീക്ഷിതമായി നിലച്ചുപോയാൽ അലർട്ട് അയക്കുന്നു
    send_telegram(f"🚨 *CRITICAL ALERT: Bot Stopped!*\nസെർവറിൽ ബോട്ടിന്റെ പ്രവർത്തനം നിലച്ചു.\nകാരണം: {fatal_crash}")
