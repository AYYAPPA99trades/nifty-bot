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

# ----------------- TELEGRAM MULTI-BOT CONFIGURATION -----------------
# രണ്ട് ബോട്ടുകളിലേക്കും ഒരേസമയം മെസ്സേജ് അയക്കാനുള്ള ടാർഗെറ്റുകൾ
TELEGRAM_TARGETS = [
    {
        "name": "Bot 1 (Your Only Alert)",
        "token": os.getenv("TELEGRAM_BOT_TOKEN_1", "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_1", "6789591588")
    },
    {
        "name": "Bot 2 (Ayyappan Alert)",
        "token": os.getenv("TELEGRAM_BOT_TOKEN_2", "8941192045:AAELQ21ZiFKnHMMySyOoMue-hzMgS9ZjotQ"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_2", "8996427731")
    }
]

STATE_FILE = "trade_state.json"
IST = pytz.timezone("Asia/Kolkata")

def send_telegram(text: str):
    """രണ്ട് ടെലിഗ്രാം അക്കൗണ്ടുകളിലേക്കും അലേർട്ടുകൾ ബ്രോഡ്കാസ്റ്റ് ചെയ്യുന്നു"""
    for target in TELEGRAM_TARGETS:
        token = target["token"]
        chat_id = target["chat_id"]
        if not token or not chat_id:
            continue
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            res = requests.post(url, json=payload, timeout=12)
            if not res.ok:
                print(f"Failed to send to {target['name']}: {res.text}")
        except Exception as e:
            print(f"Error sending to {target['name']}: {e}")

def load_state():
    """അന്നത്തെ ട്രേഡ് ഹിസ്റ്ററിയും ലൈവ് പൊസിഷനും ട്രാക്ക് ചെയ്യുന്നു"""
    today_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    default_state = {
        "date": today_str,
        "signals_count": 0,
        "max_signals": 2,
        "active_trade": None,
        "completed_trades": [],
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
        except Exception:
            pass
    return default_state

def save_state(state):
    """ഡാറ്റ സേവ് ചെയ്യുന്നു"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ----------------- DATA DOWNLOAD & INDICATORS -----------------

def get_market_data():
    ticker = "^NSEI"
    vix_ticker = "^INDIAVIX"
    df_5m = yf.download(ticker, period="5d", interval="5m", progress=False)
    df_daily = yf.download(ticker, period="3mo", interval="1d", progress=False)
    df_vix = yf.download(vix_ticker, period="5d", interval="1d", progress=False)

    for d in [df_5m, df_daily, df_vix]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    return df_5m, df_daily, df_vix

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3.0
    vol = df['Volume'].replace(0, 1)
    return (typical_price * vol).cumsum() / vol.cumsum()

# ----------------- DYNAMIC EXPIRY CALCULATION (HOLIDAY-AWARE) -----------------

def get_target_expiry_weekday(year: int, month: int, target_day: int = 3) -> datetime.date:
    """മാസത്തിലെ അവസാന നിശ്ചിത ദിവസം കണ്ടെത്തുന്നു (Thursday = 3)"""
    last_day = calendar.monthrange(year, month)[1]
    d = datetime.date(year, month, last_day)
    while d.weekday() != target_day:
        d -= datetime.timedelta(days=1)
    return d

def get_actual_expiry_date(target_date: datetime.date, trading_dates: list) -> datetime.date:
    """ഹോളിഡേ വന്നാൽ തനിയെ തൊട്ടുമുമ്പുള്ള യഥാർത്ഥ ട്രേഡിംഗ് ഡേ എക്സ്പെയറിയായി ക്രമീകരിക്കുന്നു"""
    curr = target_date
    trading_dates_set = set(trading_dates)
    while curr not in trading_dates_set and curr > (target_date - datetime.timedelta(days=10)):
        curr -= datetime.timedelta(days=1)
    return curr

# ----------------- 1. PRE-MARKET ALERT (09:08 AM) -----------------

def run_pre_market(df_daily, df_vix, state):
    prev_day = df_daily.iloc[-1]
    h, l, c = float(prev_day['High']), float(prev_day['Low']), float(prev_day['Close'])
    
    pivot = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = (pivot - bc) + pivot
    top_cpr, bottom_cpr = max(tc, bc), min(tc, bc)
    cpr_width_pct = (abs(top_cpr - bottom_cpr) / c) * 100

    if cpr_width_pct < 0.18:
        cpr_status = "🔥 Extremely Narrow (Strong Trend Potential)"
    elif cpr_width_pct > 0.35:
        cpr_status = "⚠️ Wide CPR (Range-bound/Sideways Likely)"
    else:
        cpr_status = "⚖️ Moderate CPR"

    curr_vix = float(df_vix['Close'].iloc[-1]) if not df_vix.empty else 13.5
    vix_note = "✅ Favorable for Option Buying" if curr_vix >= 13.0 else "⚠️ Low Volatility (Theta Decay Risk)"

    msg = (
        f"🌅 <b>NIFTY PRE-MARKET STRUCTURE (09:08 AM)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>CPR Status:</b> {cpr_status}\n"
        f"⚡ <b>India VIX:</b> {curr_vix:.2f} ({vix_note})\n\n"
        f"📌 <b>Key Levels:</b>\n"
        f"• Top CPR: <b>{top_cpr:.1f}</b> | Bottom CPR: <b>{bottom_cpr:.1f}</b>\n"
        f"• Prev Day High (PDH): <b>{h:.1f}</b>\n"
        f"• Prev Day Low (PDL): <b>{l:.1f}</b>\n"
        f"• Central Pivot: <b>{pivot:.1f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Plan: High conviction 15M ORB Breakout aligned with CPR direction.</i>"
    )
    send_telegram(msg)
    state["pre_market_done"] = True
    save_state(state)

# ----------------- 2 & 4. ACTIVE TRADE MANAGEMENT & RISK -----------------

def manage_active_trade(df_5m, state):
    trade = state.get("active_trade")
    if not trade:
        return False

    curr_close = float(df_5m['Close'].iloc[-1])
    curr_vwap = float(df_5m['VWAP'].iloc[-1])
    trade_type = trade["type"]
    entry = trade["entry_price"]
    sl = trade["sl"]
    target = trade["target"]
    half_target = trade["half_target"]

    if trade_type == "BUY_CE":
        if curr_close >= target and not trade.get("target_hit"):
            trade["target_hit"] = True
            msg = (
                f"🎯 <b>TARGET 1 REACHED! (NIFTY {trade['strike']} CE)</b> 💰\n\n"
                f"💵 Spot CMP: <b>{curr_close:.2f}</b>\n"
                f"✅ <b>Action:</b> Book 50% Profit now!\n"
                f"🛡️ <b>Trail SL:</b> Shift SL to Cost ({entry:.2f})"
            )
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "TARGET", "pts": target - entry})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close >= half_target and not trade.get("sl_trailed"):
            trade["sl_trailed"] = True
            trade["sl"] = entry
            msg = (
                f"🛡️ <b>TRAIL SL ALERT:</b> Reached 1:1 RRR ({curr_close:.2f}).\n"
                f"🔒 SL shifted to Entry Cost (<b>{entry:.2f}</b>). Trade is now Risk-Free!"
            )
            send_telegram(msg)
            save_state(state)

        elif curr_close < curr_vwap and (curr_close - entry) < 0:
            msg = f"⚠️ <b>EARLY EXIT:</b> Nifty slipped below VWAP ({curr_close:.2f}). Exiting to cut loss."
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "EARLY_EXIT", "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close <= sl:
            msg = f"🛑 <b>STOP LOSS HIT</b> for {trade['strike']} CE at {curr_close:.2f}."
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "SL", "pts": curr_close - entry})
            state["active_trade"] = None
            save_state(state)
            return True

    elif trade_type == "BUY_PE":
        if curr_close <= target and not trade.get("target_hit"):
            trade["target_hit"] = True
            msg = (
                f"🎯 <b>TARGET 1 REACHED! (NIFTY {trade['strike']} PE)</b> 💰\n\n"
                f"💵 Spot CMP: <b>{curr_close:.2f}</b>\n"
                f"✅ <b>Action:</b> Book 50% Profit! Trail rest to Cost."
            )
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "TARGET", "pts": entry - target})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close <= half_target and not trade.get("sl_trailed"):
            trade["sl_trailed"] = True
            trade["sl"] = entry
            msg = f"🛡️ <b>TRAIL SL:</b> Move Stop Loss to Entry Cost ({entry:.2f})."
            send_telegram(msg)
            save_state(state)

        elif curr_close > curr_vwap and (entry - curr_close) < 0:
            msg = f"⚠️ <b>EARLY EXIT:</b> Nifty crossed above VWAP ({curr_close:.2f}). Close PE trade."
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "EARLY_EXIT", "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

        elif curr_close >= sl:
            msg = f"🛑 <b>STOP LOSS HIT</b> for {trade['strike']} PE at {curr_close:.2f}."
            send_telegram(msg)
            state["completed_trades"].append({"type": trade_type, "result": "SL", "pts": entry - curr_close})
            state["active_trade"] = None
            save_state(state)
            return True

    save_state(state)
    return True

# ----------------- SCANNER & ENTRY ENGINE -----------------

def scan_for_entries(df_5m, state):
    now_ist = datetime.datetime.now(IST).time()

    # 11:30 AM - 1:30 PM Chop Zone Protection
    if datetime.time(11, 30) <= now_ist <= datetime.time(13, 30):
        print("Chop Zone Active (11:30 - 13:30). Skipping entries.")
        return

    # Max Daily Signals Cap
    if state["signals_count"] >= state["max_signals"]:
        print("Daily signal limit reached.")
        return

    curr = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    close = float(curr['Close'])
    vwap = float(curr['VWAP'])

    today_candles = df_5m.between_time("09:15", "15:30")
    if len(today_candles) < 3:
        return
    orb_high = float(today_candles.iloc[:3]['High'].max())
    orb_low = float(today_candles.iloc[:3]['Low'].min())

    atm_strike = int(round(close / 50.0) * 50)
    sl_dist = 25.0
    target_dist = 50.0

    # Bullish Call Entry
    if (close > vwap) and (close > orb_high) and (prev['Close'] <= prev['VWAP'] or curr['Low'] <= vwap):
        state["signals_count"] += 1
        state["active_trade"] = {
            "type": "BUY_CE",
            "strike": atm_strike,
            "entry_price": close,
            "sl": close - sl_dist,
            "half_target": close + (target_dist / 2),
            "target": close + target_dist,
            "sl_trailed": False,
            "target_hit": False
        }
        msg = (
            f"🚀 <b>NIFTY PRO OPTION BUY CALL (CE)</b> 🟢\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Recommended Strike:</b> NIFTY {atm_strike} CE\n"
            f"📊 <b>Spot CMP:</b> {close:.2f}\n"
            f"🛑 <b>Stop Loss:</b> {close - sl_dist:.2f} (-{sl_dist} pts)\n"
            f"🎯 <b>Target 1:</b> {close + target_dist:.2f} (+{target_dist} pts)\n"
            f"⚖️ <b>Risk-to-Reward:</b> 1:2 Strict\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: VWAP Support + 15M ORB Breakout</i>\n"
            f"⚠️ <i>Trade #{state['signals_count']} of {state['max_signals']} today</i>"
        )
        send_telegram(msg)
        save_state(state)

    # Bearish Put Entry
    elif (close < vwap) and (close < orb_low) and (prev['Close'] >= prev['VWAP'] or curr['High'] >= vwap):
        state["signals_count"] += 1
        state["active_trade"] = {
            "type": "BUY_PE",
            "strike": atm_strike,
            "entry_price": close,
            "sl": close + sl_dist,
            "half_target": close - (target_dist / 2),
            "target": close - target_dist,
            "sl_trailed": False,
            "target_hit": False
        }
        msg = (
            f"🔻 <b>NIFTY PRO OPTION BUY CALL (PE)</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Recommended Strike:</b> NIFTY {atm_strike} PE\n"
            f"📊 <b>Spot CMP:</b> {close:.2f}\n"
            f"🛑 <b>Stop Loss:</b> {close + sl_dist:.2f} (+{sl_dist} pts)\n"
            f"🎯 <b>Target 1:</b> {close - target_dist:.2f} (-{target_dist} pts)\n"
            f"⚖️ <b>Risk-to-Reward:</b> 1:2 Strict\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Setup: VWAP Breakdown + 15M ORB Breakdown</i>\n"
            f"⚠️ <i>Trade #{state['signals_count']} of {state['max_signals']} today</i>"
        )
        send_telegram(msg)
        save_state(state)

# ----------------- 5. DAILY POST-MARKET SUMMARY (03:45 PM) -----------------

def run_post_market(state):
    trades = state.get("completed_trades", [])
    total = len(trades)
    wins = len([t for t in trades if t["result"] == "TARGET"])
    losses = len([t for t in trades if t["result"] == "SL"])
    net_pts = sum([t["pts"] for t in trades])

    msg = (
        f"📋 <b>DAILY PERFORMANCE SUMMARY (03:45 PM)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Total Trades Taken: <b>{total}</b>\n"
        f"✅ Targets Hit: <b>{wins}</b>\n"
        f"🛑 Stop Losses Hit: <b>{losses}</b>\n"
        f"📊 Net Spot Points: <b>{net_pts:+.1f} pts</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏁 <i>Session ended. Resetting state for tomorrow.</i>"
    )
    send_telegram(msg)
    state["post_market_done"] = True
    save_state(state)

# ----------------- MONTHLY EXPIRY-TO-EXPIRY REPORT (HOLIDAY-PROOF) -----------------

def run_monthly_expiry_check(df_daily, state):
    trading_days = [d.date() for d in df_daily.index]
    today_date = datetime.datetime.now(IST).date()

    curr_year = today_date.year
    curr_month = today_date.month
    scheduled_day = 3  # Thursday (ചൊവ്വയാണെങ്കിൽ 1 ആക്കാം)

    this_target = get_target_expiry_weekday(curr_year, curr_month, scheduled_day)
    actual_current_expiry = get_actual_expiry_date(this_target, trading_days)

    if today_date != actual_current_expiry:
        return

    if curr_month == 1:
        prev_m, prev_y = 12, curr_year - 1
    else:
        prev_m, prev_y = curr_month - 1, curr_year

    prev_target = get_target_expiry_weekday(prev_y, prev_m, scheduled_day)
    actual_prev_expiry = get_actual_expiry_date(prev_target, trading_days)

    expiry_df = df_daily.loc[(df_daily.index.date >= actual_prev_expiry) & (df_daily.index.date <= actual_current_expiry)]
    if len(expiry_df) < 2:
        return

    open_p = float(expiry_df.iloc[0]['Close'])
    close_p = float(expiry_df.iloc[-1]['Close'])
    net_pts = close_p - open_p
    pct = (net_pts / open_p) * 100
    peak = float(expiry_df['High'].max())
    trough = float(expiry_df['Low'].min())

    holiday_alert = ""
    if actual_current_expiry != this_target:
        holiday_alert = f"\n⚠️ <i>Notice: Scheduled day was a market holiday. Expiry adjusted to {actual_current_expiry.strftime('%d-%b (%A)')}.</i>\n"

    msg = (
        f"🏁 <b>MONTHLY EXPIRY PERFORMANCE REPORT</b> 🏁\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗓 <b>Series:</b> {actual_prev_expiry.strftime('%d %b')} ➔ {actual_current_expiry.strftime('%d %b %Y')}\n"
        f"⏱ <b>Total Sessions:</b> {len(expiry_df) - 1} Trading Days\n"
        f"{holiday_alert}"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>Index Movement:</b>\n"
        f"• Base Open: <b>{open_p:.2f}</b>\n"
        f"• Expiry Close: <b>{close_p:.2f}</b>\n"
        f"• Series Peak (High): <b>{peak:.2f}</b>\n"
        f"• Series Trough (Low): <b>{trough:.2f}</b>\n"
        f"• Net Change: <b>{net_pts:+.2f} pts ({pct:+.2f}%)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <i>Contract Expired. Ready for next series.</i>"
    )
    send_telegram(msg)
    state["expiry_report_done"] = True
    save_state(state)

# ----------------- MASTER CONTROLLER -----------------

def main():
    now_ist = datetime.datetime.now(IST).time()
    state = load_state()
    df_5m, df_daily, df_vix = get_market_data()

    if df_5m.empty or df_daily.empty:
        return

    df_5m['VWAP'] = calculate_vwap(df_5m)

    # 1. Pre-Market Check (09:05 AM - 09:20 AM)
    if datetime.time(9, 5) <= now_ist < datetime.time(9, 20) and not state.get("pre_market_done"):
        run_pre_market(df_daily, df_vix, state)
        return

    # 2. Manage Existing Trade
    has_active = manage_active_trade(df_5m, state)

    # 3. Entry Scan (09:30 AM - 03:15 PM)
    if not has_active and datetime.time(9, 30) <= now_ist < datetime.time(15, 15):
        scan_for_entries(df_5m, state)

    # 4. Post-Market Summary & Expiry Check (03:35 PM onwards)
    if now_ist >= datetime.time(15, 35):
        if not state.get("post_market_done"):
            run_post_market(state)
        if not state.get("expiry_report_done"):
            run_monthly_expiry_check(df_daily, state)

if __name__ == "__main__":
    main()
