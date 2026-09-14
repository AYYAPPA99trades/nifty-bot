import os
import time
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- DUAL TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

# --- 1. WEEKEND CHECK (SATURDAY & SUNDAY) ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        f"• Today is a weekend. Market is closed.\n"
        f"• Scanner will not execute trades today.\n"
        f"• Resumes on Monday at 09:00 AM IST."
    )
    print(f"Weekend detected ({day_name}). Exiting cleanly.")
    exit(0)

# --- 2. NSE OFFICIAL HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(
                f"🏖️ MARKET HOLIDAY TODAY!\n\n"
                f"• Reason: {reason}\n"
                f"• Scanner will not run today.\n"
                f"• Bot will safely shut down."
            )
            print(f"NSE holiday detected ({reason}). Exiting cleanly.")
            exit(0)
except Exception as e:
    print(f"Holiday API check skipped/fallback: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_camarilla.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
prev_close_dict = {}
camarilla_levels = {}
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

# --- CAMARILLA PIVOT CALCULATION ---
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

            h4 = close + (diff * 1.1 / 2.0)
            h3 = close + (diff * 1.1 / 4.0)
            l3 = close - (diff * 1.1 / 4.0)
            l4 = close - (diff * 1.1 / 2.0)

            return {
                "H4": round(h4, 2),
                "H3": round(h3, 2),
                "L3": round(l3, 2),
                "L4": round(l4, 2),
                "Range": round(diff, 2)
            }
    except Exception as e:
        print(f"Camarilla Calc Error ({index_name}): {e}")
    return None

def get_historical_candles(index_name):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_hist = yf.download(ticker, period="5d", interval="5m", progress=False)
        if not df_hist.empty:
            if isinstance(df_hist.columns, pd.MultiIndex):
                df_hist.columns = df_hist.columns.get_level_values(0)
            candles = []
            for _, row in df_hist.tail(80).iterrows():
                candles.append({
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close'])
                })
            return candles
    except Exception as e:
        print(f"Historical 5m Fetch Error ({index_name}): {e}")
    return []

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

history_5m = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
current_candles_5m = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "slot": None} for idx in INDEX_WATCHLIST}
live_candles_formed = {idx: 0 for idx in INDEX_WATCHLIST}
active_trades = load_backup_state()

# --- STARTUP & MARKET STATUS ALERT (09:00 AM) ---
send_telegram_alert(
    "🚀 NIFTY & BANK NIFTY SCANNER ACTIVATED\n\n"
    "• Strategies: CAMARILLA BREAKOUT (H4 & L4)\n"
    "• Target Tracking: T1, T2, T3 Active\n"
    "• Strict SL Exit: Closes immediately upon hitting SL\n"
    "• First-Come, First-Served: Active trade blocks overlapping signals"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Live Fetch Error: {e}")
        return None

# --- MAIN EXECUTION ENGINE (09:00 AM - 03:40 PM) ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%H:%M:%S')

        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 7. MARKET CLOSING REPORT (03:40 PM)
        if current_time >= shutdown_time:
            summary = (
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                f"Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Achieved: {trade_stats['target_hits']}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}"
            )
            send_telegram_alert(summary)
            print("Daily trading completed. Bot shutting down.")
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

                    # --- ACTIVE TRADE MONITORING ---
                    trade = active_trades[index_name]
                    if trade is not None:
                        # 6. INTRADAY AUTO-EXIT ALERT (03:20 PM)
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM CLOSE)\n\n"
                                f"Strategy: {trade['strategy']}\n"
                                f"Index: {index_name}\n"
                                f"Exit Price: {current_price:.2f} | PnL: {pnl:+.2f}\n"
                                f"Status: Position Cleared."
                            )
                            active_trades[index_name] = None
                            save_backup_state(active_trades)
                            continue

                        # --- BUY TRADE TRACKING ---
                        if trade['type'] == 'BUY':
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed. Signal ended."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Current Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Book partial profit!"
                                )
                                save_backup_state(active_trades)

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Move Stop Loss to Entry (Trail SL)!"
                                )
                                save_backup_state(active_trades)

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: Full profits booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                        # --- SELL TRADE TRACKING ---
                        elif trade['type'] == 'SELL':
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed. Signal ended."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Current Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Book partial profit!"
                                )
                                save_backup_state(active_trades)

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Move Stop Loss to Entry (Trail SL)!"
                                )
                                save_backup_state(active_trades)

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: Full profits booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                    # --- 5-MINUTE CANDLE AGGREGATION ---
                    slot_5m = (now.minute // 5) * 5
                    b5 = current_candles_5m[index_name]
                    if b5["slot"] is None or b5["slot"] != slot_5m:
                        if b5["slot"] is not None and b5["open"] is not None:
                            history_5m[index_name].append({'Open': b5["open"], 'High': b5["high"], 'Low': b5["low"], 'Close': b5["close"]})
                            live_candles_formed[index_name] += 1
                            if len(history_5m[index_name]) > 120:
                                history_5m[index_name].pop(0)
                        b5["open"] = b5["high"] = b5["low"] = b5["close"] = current_price
                        b5["slot"] = slot_5m
                    else:
                        b5["high"] = max(b5["high"], current_price)
                        b5["low"] = min(b5["low"], current_price)
                        b5["close"] = current_price

                    # --- CAMARILLA BREAKOUT SIGNAL DETECTION ---
                    pivots = camarilla_levels.get(index_name)
                    # ലൈവ് സെഷനിൽ പുതിയ കാൻഡിൽ ബിൽഡ് ആയ ശേഷം മാത്രം സിഗ്നൽ എടുക്കുന്നു (പഴയ ഡാറ്റ തടയാൻ)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None and live_candles_formed[index_name] >= 1:
                        df_c = pd.DataFrame(history_5m[index_name])
                        if len(df_c) >= 2:
                            c_curr = df_c.iloc[-1]['Close']
                            c_prev = df_c.iloc[-2]['Close']

                            h4 = pivots['H4']
                            l4 = pivots['L4']
                            h3 = pivots['H3']
                            l3 = pivots['L3']

                            # BUY SIGNAL (H4 Breakout)
                            if c_prev <= h4 and c_curr > h4:
                                sl = round(h3, 2)
                                risk = round(c_curr - sl, 2)
                                if risk < 15: risk = 25.0; sl = round(c_curr - 25.0, 2)

                                t1 = round(c_curr + (risk * 1.0), 2)
                                t2 = round(c_curr + (risk * 1.5), 2)
                                t3 = round(c_curr + (risk * 2.5), 2)

                                active_trades[index_name] = {
                                    'strategy': 'CAMARILLA BREAKOUT',
                                    'type': 'BUY',
                                    'entry': c_curr,
                                    'sl': sl,
                                    't1': t1,
                                    't2': t2,
                                    't3': t3,
                                    't1_hit': False,
                                    't2_hit': False
                                }
                                save_backup_state(active_trades)
                                trade_stats['total_signals'] += 1

                                msg = (
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"⚡ Strategy: CAMARILLA BREAKOUT\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Entry: {c_curr:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )
                                send_telegram_alert(msg)

                            # SELL SIGNAL (L4 Breakdown)
                            elif c_prev >= l4 and c_curr < l4:
                                sl = round(l3, 2)
                                risk = round(sl - c_curr, 2)
                                if risk < 15: risk = 25.0; sl = round(c_curr + 25.0, 2)

                                t1 = round(c_curr - (risk * 1.0), 2)
                                t2 = round(c_curr - (risk * 1.5), 2)
                                t3 = round(c_curr - (risk * 2.5), 2)

                                active_trades[index_name] = {
                                    'strategy': 'CAMARILLA BREAKDOWN',
                                    'type': 'SELL',
                                    'entry': c_curr,
                                    'sl': sl,
                                    't1': t1,
                                    't2': t2,
                                    't3': t3,
                                    't1_hit': False,
                                    't2_hit': False
                                }
                                save_backup_state(active_trades)
                                trade_stats['total_signals'] += 1

                                msg = (
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"⚡ Strategy: CAMARILLA BREAKDOWN\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Entry: {c_curr:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )
                                send_telegram_alert(msg)

            # --- 5. HOURLY STATUS ALERT ---
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• {idx}: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(15)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(10)
