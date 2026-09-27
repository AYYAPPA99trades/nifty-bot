import datetime
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf

# ടെലഗ്രാം ക്രമീകരണങ്ങൾ
TELEGRAM_CONFIGS = [
    {
        "bot_token": "8941192045:AAELQ21ZiFKnHMMysyOoMue-hzMgS9ZjotQ",
        "chat_id": "8996427731",
        "role": "admin",
    },
    {
        "bot_token": "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8",
        "chat_id": "6789591588",
        "role": "public",
    },
]

BOT_NAME = "SAS LEVEL TRACKER"

def send_telegram_message(message, target_role="all"):
    for config in TELEGRAM_CONFIGS:
        if target_role == "admin" and config["role"] != "admin":
            continue
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        payload = {
            "chat_id": config["chat_id"],
            "text": f"🤖 *{BOT_NAME}*\n\n{message}",
            "parse_mode": "Markdown",
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            print(f"Error: {e}")

def fetch_3min_data():
    df = yf.download(tickers="^NSEI", period="2d", interval="3m")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.dropna(inplace=True)
    return df

def calculate_support_resistance(df):
    high = df["High"].max()
    low = df["Low"].min()
    close = df["Close"].iloc[-1]
    pivot = (high + low + close) / 3
    resistance_1 = (2 * pivot) - low
    support_1 = (2 * pivot) - high
    return support_1, resistance_1

def run_bot_tasks():
    now = datetime.datetime.now().time()
    market_open = datetime.time(9, 0)
    support_resistance_time = datetime.time(9, 5)
    trading_start = datetime.time(9, 15)
    trading_end = datetime.time(15, 30)

    print(f"{BOT_NAME} initialized and running...")

    # 1. 9:00 AM Auto Run Alert (അഡ്മിന് മാത്രം)
    if now >= market_open and now < support_resistance_time:
        send_telegram_message(
            "🟢 Bot auto run started successfully with zero delay backup at 9:00 AM.",
            target_role="admin",
        )

    # 2. 9:05 AM Support & Resistance (അഡ്മിനും ഗ്രൂപ്പിനും)
    if now >= support_resistance_time and now < trading_start:
        df = fetch_3min_data()
        support, resistance = calculate_support_resistance(df)
        msg = (
            f"📊 *Nifty Support & Resistance Levels*\n"
            f"Support: `{support:.2f}`\n"
            f"Resistance: `{resistance:.2f}`"
        )
        send_telegram_message(msg, target_role="all")

    # 3. 9:15 AM to 3:30 PM Trading Signals (ATR Based SL & Targets)
    if now >= trading_start and now <= trading_end:
        df = fetch_3min_data()
        if df.empty:
            return

        df["EMA_9"] = ta.ema(df["Close"], length=9)
        df["EMA_21"] = ta.ema(df["Close"], length=21)
        df["VWAP"] = ta.vwap(df["High"], df["Low"], df["Close"], df["Volume"])
        df["ATR"] = ta.atr(df["High"], df["Low"], df["Close"], length=14)

        last_row = df.iloc[-2]
        close_price = last_row["Close"]
        vwap = last_row["VWAP"]
        ema9 = last_row["EMA_9"]
        ema21 = last_row["EMA_21"]
        atr = last_row["ATR"]

        signal = 0
        if close_price > vwap and ema9 > ema21:
            signal = 1
        elif close_price < vwap and ema9 < ema21:
            signal = -1

        timestamp = df.index[-2]

        # ATR അടിസ്ഥാനമാക്കിയുള്ള ടാർഗെറ്റും സ്റ്റോപ്പ് ലോസും
        if signal == 1:
            entry = close_price
            sl = entry - (1.0 * atr)       # ATR അടിസ്ഥാനമാക്കിയുള്ള SL
            t1 = entry + (1.0 * atr)       # T1 (1:1 Risk-Reward)
            t2 = entry + (2.0 * atr)       # T2 (1:2 Risk-Reward)
            t3 = entry + (3.0 * atr)       # T3 (1:3 Risk-Reward)

            msg = (
                f"🚀 *BUY SIGNAL* 🚀\n"
                f"⏰ Time: `{timestamp}`\n"
                f"💰 Entry Price: `{entry:.2f}`\n"
                f"🎯 T1: `{t1:.2f}`\n"
                f"🎯 T2: `{t2:.2f}`\n"
                f"🎯 T3: `{t3:.2f}`\n"
                f"🛡️ SL: `{sl:.2f}`"
            )
            send_telegram_message(msg, target_role="all")

        elif signal == -1:
            entry = close_price
            sl = entry + (1.0 * atr)       # ATR അടിസ്ഥാനമാക്കിയുള്ള SL
            t1 = entry - (1.0 * atr)       # T1
            t2 = entry - (2.0 * atr)       # T2
            t3 = entry - (3.0 * atr)       # T3

            msg = (
                f"🔻 *SELL SIGNAL* 🔻\n"
                f"⏰ Time: `{timestamp}`\n"
                f"💰 Entry Price: `{entry:.2f}`\n"
                f"🎯 T1: `{t1:.2f}`\n"
                f"🎯 T2: `{t2:.2f}`\n"
                f"🎯 T3: `{t3:.2f}`\n"
                f"🛡️ SL: `{sl:.2f}`"
            )
            send_telegram_message(msg, target_role="all")

if __name__ == "__main__":
    run_bot_tasks()
