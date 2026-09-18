import os
import time
import threading
import requests
import yfinance as yf
import pandas_ta as ta
from http.server import HTTPServer, BaseHTTPRequestHandler

# 1. Render Port Binding Server (Render ഷട്ട്ഡൗൺ ആകാതിരിക്കാൻ)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is Running Perfectly!")

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# 2. Telegram Alert Function
BOT1_TOKEN = os.getenv("BOT1_TOKEN")
CHANNEL_ID_1 = os.getenv("CHANNEL_ID_1")

def send_telegram_alert(message):
    if BOT1_TOKEN and CHANNEL_ID_1:
        url = f"https://api.telegram.org/bot{BOT1_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHANNEL_ID_1,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Telegram Error: {e}")

# 3. Strategy Logic (5m Supertrend + ATR)
def run_nifty_scanner():
    last_signal = None
    
    while True:
        try:
            # 5 മിനിറ്റ് Nifty ഡാറ്റ എടുക്കുന്നു
            df = yf.download("^NSEI", period="5d", interval="5m", progress=False)
            
            if not df.empty and len(df) >= 30:
                # Multi-index headers ഒഴിവാക്കാൻ
                if isinstance(df.columns, tuple) or getattr(df.columns, 'nlevels', 1) > 1:
                    df.columns = [col[0] for col in df.columns]

                # Indicators
                df['EMA200'] = ta.ema(df['Close'], length=200)
                df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
                
                # Supertrend (10, 2)
                st_df = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=2.0)
                # സൂപ്പർട്രെൻഡ് ഡയറക്ഷൻ കോളം കണ്ടെത്തുന്നു
                dir_col = [c for c in st_df.columns if 'SUPERTd' in c][0]
                df['ST_DIR'] = st_df[dir_col]

                # അവസാനമായി പൂർത്തിയായ കാൻഡിൽ
                curr = df.iloc[-2]
                prev = df.iloc[-3]

                curr_close = float(curr['Close'])
                curr_atr = float(curr['ATR'])
                curr_ema = float(curr['EMA200']) if not pd.isna(curr['EMA200']) else 0

                # Buy CE Signal (Supertrend Flip to Green & Above 200 EMA)
                if prev['ST_DIR'] == -1 and curr['ST_DIR'] == 1 and curr_close > curr_ema:
                    if last_signal != "BUY":
                        sl = round(curr_close - (1.2 * curr_atr), 1)
                        target = round(curr_close + (2.4 * curr_atr), 1)
                        msg = (
                            f"🟢 *NIFTY 50 - BUY CALL (CE)*\n\n"
                            f"📈 Entry: `{curr_close:.1f}`\n"
                            f"🛑 SL: `{sl}`\n"
                            f"🎯 Target: `{target}`\n"
                            f"📊 ATR: `{curr_atr:.1f}`"
                        )
                        send_telegram_alert(msg)
                        last_signal = "BUY"

                # Buy PE Signal (Supertrend Flip to Red & Below 200 EMA)
                elif prev['ST_DIR'] == 1 and curr['ST_DIR'] == -1 and (curr_ema == 0 or curr_close < curr_ema):
                    if last_signal != "SELL":
                        sl = round(curr_close + (1.2 * curr_atr), 1)
                        target = round(curr_close - (2.4 * curr_atr), 1)
                        msg = (
                            f"🔴 *NIFTY 50 - BUY PUT (PE)*\n\n"
                            f"📉 Entry: `{curr_close:.1f}`\n"
                            f"🛑 SL: `{sl}`\n"
                            f"🎯 Target: `{target}`\n"
                            f"📊 ATR: `{curr_atr:.1f}`"
                        )
                        send_telegram_alert(msg)
                        last_signal = "SELL"

        except Exception as err:
            print(f"Loop Error: {err}")

        # ഓരോ 60 സെക്കൻഡിലും റീഫ്രഷ് ചെയ്യുന്നു
        time.sleep(60)

if __name__ == "__main__":
    import pandas as pd
    # Health check server ബാക്ക്ഗ്രൗണ്ട് ത്രെഡിൽ തുടങ്ങുന്നു
    threading.Thread(target=start_health_server, daemon=True).start()
    print("Bot Service Initialized Successfully.")
    
    # മെയിൻ ലൂപ്പ് റൺ ചെയ്യുന്നു
    run_nifty_scanner()
