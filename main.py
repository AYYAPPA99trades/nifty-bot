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
            payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
            tele_session.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Delivery Error ({chat_id}): {e}")

STRATEGY_DISPLAY_NAME = "CAMARILLA BREAKOUT"

# --- 1. STARTUP ALERT (09:00 AM) ---
send_telegram_alert(
    "🚀 *NIFTY & BANK NIFTY SCANNER ACTIVATED*\n\n"
    f"• *Strategy:* {STRATEGY_DISPLAY_NAME} (R4 / S4)\n"
    "• *Trading Hours:* 09:30 AM - 03:20 PM IST\n"
    "• *Special Feature:* HERO-ZERO Engine Active on Expiry Days (01:15 PM - 03:00 PM)\n"
    "• *Risk Engine:* T1 Breakeven Trail + Reversal Profit Lock Active"
)

# --- 2. WEEKEND CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ *WEEKEND MARKET HOLIDAY ({day_name})!*\n\n"
        "• Today is a weekend. Market is closed.\n"
        "• Scanner will not run today.\n"
        "• Resumes on Monday at 09:00 AM IST."
    )
    exit(0)

# --- 3. NSE OFFICIAL HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ *MARKET HOLIDAY TODAY!*\n\nReason: {reason}\nScanner will not run today.")
            exit(0)
except Exception as e:
    print(f"Holiday API check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_camarilla.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0, "early_sl_cuts": 0}
prev_close_dict = {}
camarilla_levels = {}
last_heartbeat_hour = -1
levels_sent_today = False

# --- STATE BACKUP ---
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

# --- CAMARILLA PIVOT ENGINE ---
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
                "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2), "S4": round(s4, 2)
            }
    except Exception as e:
        print(f"Camarilla Error ({index_name}): {e}")
    return None

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

active_trades = load_backup_state()

# --- HERO-ZERO STRIKE SELECTOR (₹15 - ₹35 RANGE) ---
def get_hero_zero_option(index_name, signal_direction):
    symbol = "NIFTY" if index_name == "NIFTY 50" else "BANKNIFTY"
    opt_type = "CE" if signal_direction == "BUY" else "PE"
    try:
        chain_df = capital_market.live_index_option_chain(symbol)
        if chain_df is not None and not chain_df.empty:
            exp_date = chain_df['expiryDate'].iloc[0]
            curr_exp_df = chain_df[chain_df['expiryDate'] == exp_date]
            
            ltp_col = f"{opt_type}_LTP"
            candidates = []
            for _, row in curr_exp_df.iterrows():
                try:
                    ltp = float(str(row[ltp_col]).replace(',', ''))
                    if 15.0 <= ltp <= 35.0:
                        strike = int(row['strikePrice'])
                        candidates.append((strike, ltp))
                except:
                    continue
            
            if candidates:
                # Select the strike closest to ₹25
                best_match = min(candidates, key=lambda x: abs(x[1] - 25.0))
                return f"{best_match[0]} {opt_type}", best_match[1], exp_date
    except Exception as e:
        print(f"Hero Zero Fetch Error: {e}")
    return None, None, None

# --- REGULAR OPTION ENGINE ---
def get_option_recommendations(index_name, spot_price, signal_direction):
    step = 50 if index_name == "NIFTY 50" else 100
    atm_strike = int(round(spot_price / step) * step)

    if signal_direction == "BUY":
        buyer_type = "CE"
        buyer_strike = atm_strike
        seller_type = "PE"
        seller_strike = atm_strike
        safe_seller_strike = atm_strike - step
    else:
        buyer_type = "PE"
        buyer_strike = atm_strike
        seller_type = "CE"
        seller_strike = atm_strike
        safe_seller_strike = atm_strike + step

    symbol = "NIFTY" if index_name == "NIFTY 50" else "BANKNIFTY"
    buyer_ltp = None
    seller_ltp = None
    safe_seller_ltp = None
    exp_date = ""

    try:
        chain_df = capital_market.live_index_option_chain(symbol)
        if chain_df is not None and not chain_df.empty:
            exp_date = chain_df['expiryDate'].iloc[0]
            curr_exp_df = chain_df[chain_df['expiryDate'] == exp_date]

            b_row = curr_exp_df[curr_exp_df['strikePrice'] == buyer_strike]
            if not b_row.empty and f"{buyer_type}_LTP" in b_row.columns:
                buyer_ltp = float(str(b_row[f"{buyer_type}_LTP"].values[0]).replace(',', ''))

            s_row = curr_exp_df[curr_exp_df['strikePrice'] == seller_strike]
            if not s_row.empty and f"{seller_type}_LTP" in s_row.columns:
                seller_ltp = float(str(s_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))

            safe_row = curr_exp_df[curr_exp_df['strikePrice'] == safe_seller_strike]
            if not safe_row.empty and f"{seller_type}_LTP" in safe_row.columns:
                safe_seller_ltp = float(str(safe_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))
    except Exception as e:
        print(f"Option Chain Fetch Warning: {e}")

    return {
        "exp": exp_date,
        "buyer_strike": f"{buyer_strike} {buyer_type}",
        "buyer_ltp": f"₹{buyer_ltp:.2f}" if buyer_ltp else "Check App",
        "seller_strike": f"{seller_strike} {seller_type}",
        "seller_ltp": f"₹{seller_ltp:.2f}" if seller_ltp else "Check App",
        "safe_seller_strike": f"{safe_seller_strike} {seller_type}",
        "safe_seller_ltp": f"₹{safe_seller_ltp:.2f}" if safe_seller_ltp else "Check App",
    }

# --- 09:10 AM MORNING LEVELS ---
def send_morning_levels():
    msg = "📊 *KEY SUPPORT & RESISTANCE (CAMARILLA)*\n⏰ Time: 09:10 AM IST\n\n"
    for idx in INDEX_WATCHLIST:
        p = camarilla_levels.get(idx)
        if p:
            msg += (
                f"🔹 *{idx} LEVELS:*\n"
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

# --- MAIN EXECUTION ENGINE ---
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

        # Capital Protection
        daily_loss_count = trade_stats['sl_hits'] + trade_stats.get('early_sl_cuts', 0)
        if daily_loss_count >= 2:
            can_take_trades = False

        # HERO-ZERO EXPLICIT TIMING WINDOW (01:15 PM - 03:00 PM)
        weekday = now.weekday() # 1 = Tuesday (BankNifty), 3 = Thursday (Nifty)
        is_hero_zero_window = (datetime.strptime("13:15", "%H:%M").time() <= current_time <= datetime.strptime("15:00", "%H:%M").time())

        # 09:10 AM Levels Dispatch
        if now.hour == 9 and now.minute >= 10 and not levels_sent_today:
            send_morning_levels()
            levels_sent_today = True

        # 03:40 PM Clean Shutdown & Win Rate
        if current_time >= shutdown_time:
            total_closed = trade_stats['target_hits'] + trade_stats['sl_hits']
            win_rate = (trade_stats['target_hits'] / total_closed * 100) if total_closed > 0 else 0.0

            summary = (
                f"📊 *MARKET CLOSED (DAILY REPORT)*\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Achieved: {trade_stats['target_hits']}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n"
                f"• Early Cuts: {trade_stats['early_sl_cuts']}\n"
                f"🏆 *Win Rate:* {win_rate:.1f}%"
            )
            send_telegram_alert(summary)
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

                    # 1. TRADE MANAGEMENT ENGINE
                    trade = active_trades[index_name]
                    if trade is not None:
                        # 03:20 PM Auto-Exit
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"⏰ *AUTO EXIT (03:20 PM CLOSE)*\n\n"
                                f"Strategy: {trade['strategy']}\n"
                                f"Index: *{index_name}*\n"
                                f"Exit Price: {current_price:.2f} | PnL: {pnl:+.2f}\n"
                                f"Status: Position Cleared."
                            )
                            active_trades[index_name] = None
                            save_backup_state(active_trades)
                            continue

                        # --- BUY TRADE MONITORING ---
                        if trade['type'] == 'BUY':
                            if 'best_price' not in trade:
                                trade['best_price'] = trade['entry']
                            trade['best_price'] = max(trade['best_price'], current_price)
                            peak_profit = trade['best_price'] - trade['entry']

                            # Early Reversal Exit
                            pivots = camarilla_levels.get(index_name)
                            if pivots and current_price < pivots['R3'] and not trade.get('t1_hit') and peak_profit < 15:
                                cut_pts = current_price - trade['entry']
                                trade_stats['early_sl_cuts'] += 1
                                send_telegram_alert(
                                    f"⚠️ *SIGNAL INVALIDATED: EARLY EXIT!*\n\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Reason: False Breakout below R3\n"
                                    f"Exit Price: {current_price:.2f}\n"
                                    f"Cut at: {cut_pts:+.2f} pts (Saved large SL)\n"
                                    f"Status: Trade Closed safely."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # Reversal Profit Lock
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                pullback = trade['best_price'] - current_price
                                if pullback >= (peak_profit * 0.40):
                                    locked_gain = current_price - trade['entry']
                                    send_telegram_alert(
                                        f"⚡ *MARKET REVERSAL: BOOK FULL PROFIT!*\n\n"
                                        f"Strategy: {trade['strategy']}\n"
                                        f"Index: *{index_name}* (BUY)\n"
                                        f"Peak Price: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ *{current_price:.2f}*\n"
                                        f"Points Captured: {locked_gain:+.2f}\n"
                                        f"Status: Trade Closed in profit before SL."
                                    )
                                    trade_stats['target_hits'] += 1
                                    active_trades[index_name] = None
                                    save_backup_state(active_trades)
                                    continue

                            # Stop Loss Hit
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ *STOP LOSS HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # Target 1 Hit -> Trail SL to Entry
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"🛡️ *SL Trailed to Entry:* {trade['entry']:.2f} (Zero Risk Active)"
                                )
                                save_backup_state(active_trades)

                            # Target 2 Hit
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Target 2 Reached!"
                                )
                                save_backup_state(active_trades)

                            # Final Target 3 Hit
                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All targets completed. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                        # --- SELL TRADE MONITORING ---
                        elif trade['type'] == 'SELL':
                            if 'best_price' not in trade:
                                trade['best_price'] = trade['entry']
                            trade['best_price'] = min(trade['best_price'], current_price)
                            peak_profit = trade['entry'] - trade['best_price']

                            # Early Reversal Exit
                            pivots = camarilla_levels.get(index_name)
                            if pivots and current_price > pivots['S3'] and not trade.get('t1_hit') and peak_profit < 15:
                                cut_pts = trade['entry'] - current_price
                                trade_stats['early_sl_cuts'] += 1
                                send_telegram_alert(
                                    f"⚠️ *SIGNAL INVALIDATED: EARLY EXIT!*\n\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Reason: False Breakdown above S3\n"
                                    f"Exit Price: {current_price:.2f}\n"
                                    f"Cut at: {cut_pts:+.2f} pts (Saved large SL)\n"
                                    f"Status: Trade Closed safely."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # Reversal Profit Lock
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                bounce = current_price - trade['best_price']
                                if bounce >= (peak_profit * 0.40):
                                    locked_gain = trade['entry'] - current_price
                                    send_telegram_alert(
                                        f"⚡ *MARKET REVERSAL: BOOK FULL PROFIT!*\n\n"
                                        f"Strategy: {trade['strategy']}\n"
                                        f"Index: *{index_name}* (SELL)\n"
                                        f"Lowest Dip: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ *{current_price:.2f}*\n"
                                        f"Points Captured: {locked_gain:+.2f}\n"
                                        f"Status: Trade Closed in profit before SL."
                                    )
                                    trade_stats['target_hits'] += 1
                                    active_trades[index_name] = None
                                    save_backup_state(active_trades)
                                    continue

                            # Stop Loss Hit
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ *STOP LOSS HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            # Target 1 Hit -> Trail SL to Entry
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"🛡️ *SL Trailed to Entry:* {trade['entry']:.2f} (Zero Risk Active)"
                                )
                                save_backup_state(active_trades)

                            # Target 2 Hit
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Target 2 Reached!"
                                )
                                save_backup_state(active_trades)

                            # Final Target 3 Hit
                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All targets completed. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                    # 2. ENTRY DETECTOR (REGULAR & HERO-ZERO)
                    pivots = camarilla_levels.get(index_name)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        r4 = pivots['R4']
                        r3 = pivots['R3']
                        s3 = pivots['S3']
                        s4 = pivots['S4']

                        is_expiry_day = (weekday == 1 and index_name == "NIFTY BANK") or (weekday == 3 and index_name == "NIFTY 50")

                        # --- BUY ENTRY ---
                        if current_price > r4:
                            # Hero-Zero Trigger on Expiry Days (01:15 PM - 03:00 PM)
                            if is_expiry_day and is_hero_zero_window:
                                hz_strike, hz_ltp, hz_exp = get_hero_zero_option(index_name, "BUY")
                                if hz_ltp:
                                    sl_pts = 15.0
                                    active_trades[index_name] = {
                                        'strategy': 'HERO OR ZERO',
                                        'type': 'BUY',
                                        'entry': current_price,
                                        'best_price': current_price,
                                        'sl': round(current_price - sl_pts, 2),
                                        't1': round(current_price + sl_pts, 2),
                                        't2': round(current_price + (sl_pts * 2), 2),
                                        't3': round(current_price + (sl_pts * 3.5), 2),
                                        't1_hit': False,
                                        't2_hit': False
                                    }
                                    save_backup_state(active_trades)
                                    trade_stats['total_signals'] += 1

                                    hz_sl = max(1.0, round(hz_ltp * 0.4, 1))
                                    hz_t1 = round(hz_ltp * 2.0, 1)
                                    hz_t2 = round(hz_ltp * 3.0, 1)
                                    hz_t3 = round(hz_ltp * 5.0, 1)

                                    msg = (
                                        f"🚀 *HERO OR ZERO EXPIRY SIGNAL!*\n\n"
                                        f"⚡ Strategy: EXPIRY MOMENTUM\n"
                                        f"⏰ Time: {current_time_str} IST\n"
                                        f"📌 Index: *{index_name}* (BUY CALL)\n"
                                        f"💵 Spot Entry: {current_price:.2f}\n\n"
                                        f"🎯 *Recommended Strike:* *{hz_strike}*\n"
                                        f"💰 *Entry Premium:* ₹{hz_ltp:.2f}\n"
                                        f"🛑 *Strict SL:* ₹{hz_sl:.2f} (Risk Defined)\n\n"
                                        f"🚀 *Target 1 (2X):* ₹{hz_t1:.2f}\n"
                                        f"🚀 *Target 2 (3X):* ₹{hz_t2:.2f}\n"
                                        f"🚀 *Target 3 (Moonshot):* ₹{hz_t3:.2f}+\n\n"
                                        f"⚠️ _High Risk - High Reward Trade. Use small capital!_"
                                    )
                                    send_telegram_alert(msg)
                                    continue

                            # Regular Buy Trigger
                            sl = round(r3, 2)
                            risk = round(current_price - sl, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price - 25.0, 2)

                            t1 = round(current_price + (risk * 1.0), 2)
                            t2 = round(current_price + (risk * 1.5), 2)
                            t3 = round(current_price + (risk * 2.5), 2)

                            opt = get_option_recommendations(index_name, current_price, "BUY")
                            exp_txt = f"({opt['exp']})" if opt['exp'] else ""

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
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            msg = (
                                f"🟢 *{index_name} BUY SIGNAL*\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: {current_price:.2f}\n"
                                f"🛑 Spot SL: {sl:.2f}\n\n"
                                f"🛒 *FOR OPTION BUYERS:* {exp_txt}\n"
                                f"• Buy: *{opt['buyer_strike']}* @ {opt['buyer_ltp']}\n\n"
                                f"🛡️ *FOR OPTION SELLERS:* (Decay Advantage)\n"
                                f"• Sell ATM: *{opt['seller_strike']}* @ {opt['seller_ltp']}\n"
                                f"• Safe OTM: *{opt['safe_seller_strike']}* @ {opt['safe_seller_ltp']}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )
                            send_telegram_alert(msg)

                        # --- SELL ENTRY ---
                        elif current_price < s4:
                            # Hero-Zero Trigger on Expiry Days (01:15 PM - 03:00 PM)
                            if is_expiry_day and is_hero_zero_window:
                                hz_strike, hz_ltp, hz_exp = get_hero_zero_option(index_name, "SELL")
                                if hz_ltp:
                                    sl_pts = 15.0
                                    active_trades[index_name] = {
                                        'strategy': 'HERO OR ZERO',
                                        'type': 'SELL',
                                        'entry': current_price,
                                        'best_price': current_price,
                                        'sl': round(current_price + sl_pts, 2),
                                        't1': round(current_price - sl_pts, 2),
                                        't2': round(current_price - (sl_pts * 2), 2),
                                        't3': round(current_price - (sl_pts * 3.5), 2),
                                        't1_hit': False,
                                        't2_hit': False
                                    }
                                    save_backup_state(active_trades)
                                    trade_stats['total_signals'] += 1

                                    hz_sl = max(1.0, round(hz_ltp * 0.4, 1))
                                    hz_t1 = round(hz_ltp * 2.0, 1)
                                    hz_t2 = round(hz_ltp * 3.0, 1)
                                    hz_t3 = round(hz_ltp * 5.0, 1)

                                    msg = (
                                        f"🚀 *HERO OR ZERO EXPIRY SIGNAL!*\n\n"
                                        f"⚡ Strategy: EXPIRY MOMENTUM\n"
                                        f"⏰ Time: {current_time_str} IST\n"
                                        f"📌 Index: *{index_name}* (BUY PUT)\n"
                                        f"💵 Spot Entry: {current_price:.2f}\n\n"
                                        f"🎯 *Recommended Strike:* *{hz_strike}*\n"
                                        f"💰 *Entry Premium:* ₹{hz_ltp:.2f}\n"
                                        f"🛑 *Strict SL:* ₹{hz_sl:.2f} (Risk Defined)\n\n"
                                        f"🚀 *Target 1 (2X):* ₹{hz_t1:.2f}\n"
                                        f"🚀 *Target 2 (3X):* ₹{hz_t2:.2f}\n"
                                        f"🚀 *Target 3 (Moonshot):* ₹{hz_t3:.2f}+\n\n"
                                        f"⚠️ _High Risk - High Reward Trade. Use small capital!_"
                                    )
                                    send_telegram_alert(msg)
                                    continue

                            # Regular Sell Trigger
                            sl = round(s3, 2)
                            risk = round(sl - current_price, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price + 25.0, 2)

                            t1 = round(current_price - (risk * 1.0), 2)
                            t2 = round(current_price - (risk * 1.5), 2)
                            t3 = round(current_price - (risk * 2.5), 2)

                            opt = get_option_recommendations(index_name, current_price, "SELL")
                            exp_txt = f"({opt['exp']})" if opt['exp'] else ""

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
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            msg = (
                                f"🔴 *{index_name} SELL SIGNAL*\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: {current_price:.2f}\n"
                                f"🛑 Spot SL: {sl:.2f}\n\n"
                                f"🛒 *FOR OPTION BUYERS:* {exp_txt}\n"
                                f"• Buy: *{opt['buyer_strike']}* @ {opt['buyer_ltp']}\n\n"
                                f"🛡️ *FOR OPTION SELLERS:* (Decay Advantage)\n"
                                f"• Sell ATM: *{opt['seller_strike']}* @ {opt['seller_ltp']}\n"
                                f"• Safe OTM: *{opt['safe_seller_strike']}* @ {opt['safe_seller_ltp']}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )
                            send_telegram_alert(msg)

            # 3. HOURLY STATUS ALERT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 *HOURLY STATUS ALERT*\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• *{idx}:* {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(3)

    except Exception as loop_err:
        print(f"Engine Loop Warning: {loop_err}")
        time.sleep(3)
