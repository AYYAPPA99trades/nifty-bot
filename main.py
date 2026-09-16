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

tele_session = requests.Session()

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            tele_session.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

STRATEGY_DISPLAY_NAME = "QUANTUM MOMENTUM"

# --- 1. WEEKEND CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        f"• Market is closed today.\n"
        f"• Scanner will resume on Monday at 09:00 AM IST."
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
                f"🏖️ MARKET HOLIDAY TODAY!\n\n"
                f"• Reason: {reason}\n"
                f"• Scanner will safely shut down."
            )
            exit(0)
except Exception as e:
    print(f"Holiday API check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_camarilla.json"

# --- FULL PERSISTENT BACKUP SYSTEM ---
def load_backup():
    default_data = {
        "trades": {idx: None for idx in INDEX_WATCHLIST},
        "stats": {
            "total_signals": 0,
            "targets_achieved": 0,
            "sl_hits": 0,
            "reversal_profits": 0
        },
        "date": datetime.now(IST).strftime('%d-%b-%Y')
    }
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                # Reset stats if backup is from a previous day
                if data.get("date") == default_data["date"]:
                    return data.get("trades", default_data["trades"]), data.get("stats", default_data["stats"])
        except Exception as err:
            print(f"Backup Load Error: {err}")
    return default_data["trades"], default_data["stats"]

def save_backup(trades, stats):
    try:
        data = {
            "trades": trades,
            "stats": stats,
            "date": datetime.now(IST).strftime('%d-%b-%Y')
        }
        with open(BACKUP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as err:
        print(f"Backup Save Error: {err}")

active_trades, trade_stats = load_backup()

# --- CAMARILLA PIVOT CALCULATION (INSTANT HISTORICAL DATA) ---
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

            return {
                "R4": round(close + (diff * 1.1 / 2.0), 2),
                "R3": round(close + (diff * 1.1 / 4.0), 2),
                "R2": round(close + (diff * 1.1 / 6.0), 2),
                "R1": round(close + (diff * 1.1 / 12.0), 2),
                "S1": round(close - (diff * 1.1 / 12.0), 2),
                "S2": round(close - (diff * 1.1 / 6.0), 2),
                "S3": round(close - (diff * 1.1 / 4.0), 2),
                "S4": round(close - (diff * 1.1 / 2.0), 2)
            }
    except Exception as e:
        print(f"Camarilla Error ({index_name}): {e}")
    return None

camarilla_levels = {idx: calculate_camarilla_pivots(idx) for idx in INDEX_WATCHLIST}

# --- STARTUP ALERT ---
send_telegram_alert(
    "🚀 NIFTY & BANK NIFTY SCANNER ONLINE\n\n"
    f"• Strategy: {STRATEGY_DISPLAY_NAME}\n"
    "• Operating Window: 09:00 AM - 03:40 PM (Continuous)\n"
    "• Feature: Reversal Profit Auto-Booking Enabled\n"
    f"• Restored Active Trades: {sum(1 for v in active_trades.values() if v is not None)}"
)

def send_morning_levels():
    msg = "📊 KEY SUPPORT & RESISTANCE LEVELS\n⏰ Time: 09:10 AM IST\n\n"
    for idx in INDEX_WATCHLIST:
        p = camarilla_levels.get(idx)
        if p:
            msg += (
                f"🔹 {idx} LEVELS:\n"
                f"• R4 (Breakout Buy): {p['R4']:.2f}\n"
                f"• R3 (Key Resistance): {p['R3']:.2f}\n"
                f"• S3 (Key Support): {p['S3']:.2f}\n"
                f"• S4 (Breakdown Sell): {p['S4']:.2f}\n\n"
            )
    send_telegram_alert(msg)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Live Fetch Error: {e}")
        return None

prev_close_dict = {}
last_heartbeat_hour = -1
levels_sent_today = False

# --- CONTINUOUS MAIN RUNNER (09:00 AM TO 03:40 PM) ---
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

        # 1. 09:10 AM LEVELS
        if now.hour == 9 and now.minute >= 10 and not levels_sent_today:
            send_morning_levels()
            levels_sent_today = True

        # 2. 03:40 PM FINAL SHUTDOWN & ACCURATE REPORT
        if current_time >= shutdown_time:
            total_sigs = trade_stats['total_signals']
            targets = trade_stats['targets_achieved']
            sls = trade_stats['sl_hits']
            revs = trade_stats['reversal_profits']
            total_resolved = targets + sls + revs
            win_rate = ((targets + revs) / total_resolved * 100) if total_resolved > 0 else 0.0

            summary = (
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {total_sigs}\n"
                f"• Targets Achieved: {targets}\n"
                f"• Stop Losses Hit: {sls}\n"
                f"• Reversal Exits in Profit: {revs}\n"
                f"• Win Rate: {win_rate:.1f}%"
            )
            send_telegram_alert(summary)
            print("Day finished successfully. Bot shutting down.")
            break

        # 3. LIVE TICK PROCESSING
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

                    trade = active_trades[index_name]

                    # --- ACTIVE TRADE TRACKING ---
                    if trade is not None:
                        # 03:20 PM Square Off
                        if is_market_closing:
                            if not trade.get('t1_hit'):
                                pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                                send_telegram_alert(
                                    f"⏰ AUTO EXIT (03:20 PM CLOSE)\n\n"
                                    f"Index: {index_name}\n"
                                    f"Exit Price: {current_price:.2f} | PnL: {pnl:+.2f}\n"
                                    f"Status: Position Closed."
                                )
                            active_trades[index_name] = None
                            save_backup(active_trades, trade_stats)
                            continue

                        # BUY TRADE
                        if trade['type'] == 'BUY':
                            if 'best_price' not in trade:
                                trade['best_price'] = trade['entry']
                            trade['best_price'] = max(trade['best_price'], current_price)
                            peak_profit = trade['best_price'] - trade['entry']

                            # Early Profit Booking on Reversal
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                pullback = trade['best_price'] - current_price
                                if pullback >= (peak_profit * 0.40):
                                    locked_gain = current_price - trade['entry']
                                    send_telegram_alert(
                                        f"⚡ MARKET REVERSAL: BOOK FULL PROFIT!\n\n"
                                        f"Strategy: {trade['strategy']}\n"
                                        f"Index: {index_name} (BUY)\n"
                                        f"Peak Price: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ {current_price:.2f}\n"
                                        f"Points Captured: {locked_gain:+.2f}\n"
                                        f"Status: Trade Closed before reaching SL."
                                    )
                                    trade_stats['reversal_profits'] += 1
                                    active_trades[index_name] = None
                                    save_backup(active_trades, trade_stats)
                                    continue

                            # SL Hit
                            if not trade.get('t1_hit') and current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # Target 1 Hit
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['targets_achieved'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Partial Profit Booked. SL Disabled."
                                )
                                save_backup(active_trades, trade_stats)

                            # Target 2 Hit
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Price: {current_price:.2f} | T2: {trade['t2']:.2f}"
                                )
                                save_backup(active_trades, trade_stats)

                            # Target 3 Hit
                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All targets completed. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                        # SELL TRADE
                        elif trade['type'] == 'SELL':
                            if 'best_price' not in trade:
                                trade['best_price'] = trade['entry']
                            trade['best_price'] = min(trade['best_price'], current_price)
                            peak_profit = trade['entry'] - trade['best_price']

                            # Early Profit Booking on Reversal
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                bounce = current_price - trade['best_price']
                                if bounce >= (peak_profit * 0.40):
                                    locked_gain = trade['entry'] - current_price
                                    send_telegram_alert(
                                        f"⚡ MARKET REVERSAL: BOOK FULL PROFIT!\n\n"
                                        f"Strategy: {trade['strategy']}\n"
                                        f"Index: {index_name} (SELL)\n"
                                        f"Lowest Dip: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ {current_price:.2f}\n"
                                        f"Points Captured: {locked_gain:+.2f}\n"
                                        f"Status: Trade Closed before reaching SL."
                                    )
                                    trade_stats['reversal_profits'] += 1
                                    active_trades[index_name] = None
                                    save_backup(active_trades, trade_stats)
                                    continue

                            # SL Hit
                            if not trade.get('t1_hit') and current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # Target 1 Hit
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['targets_achieved'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Partial Profit Booked. SL Disabled."
                                )
                                save_backup(active_trades, trade_stats)

                            # Target 2 Hit
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Price: {current_price:.2f} | T2: {trade['t2']:.2f}"
                                )
                                save_backup(active_trades, trade_stats)

                            # Target 3 Hit
                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All targets completed. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                    # --- NEW SIGNAL SCANNING ---
                    pivots = camarilla_levels.get(index_name)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        r4, r3 = pivots['R4'], pivots['R3']
                        s3, s4 = pivots['S3'], pivots['S4']

                        # BUY BREAKOUT
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
                                'best_price': current_price,
                                'sl': sl,
                                't1': t1,
                                't2': t2,
                                't3': t3,
                                't1_hit': False,
                                't2_hit': False
                            }
                            trade_stats['total_signals'] += 1
                            save_backup(active_trades, trade_stats)

                            send_telegram_alert(
                                f"🟢 {index_name} BUY SIGNAL\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )

                        # SELL BREAKDOWN
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
                                'best_price': current_price,
                                'sl': sl,
                                't1': t1,
                                't2': t2,
                                't3': t3,
                                't1_hit': False,
                                't2_hit': False
                            }
                            trade_stats['total_signals'] += 1
                            save_backup(active_trades, trade_stats)

                            send_telegram_alert(
                                f"🔴 {index_name} SELL SIGNAL\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )

            # 4. HOURLY STATUS REPORT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• {idx}: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(3)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(3)
