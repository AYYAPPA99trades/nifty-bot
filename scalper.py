import os
import json
import time
import smtplib
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

import pytz
import yfinance as yf
import pandas as pd
import ta
import requests
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

STATE_FILE = "trade_state.json"
DATA_LOG_FILE = "trade_history.json"

ADMIN_EMAIL_ADDRESS = "Shinos99@gmail.com"
ADMIN_EMAIL_PASSWORD = "Qm1mu8xU"

TELEGRAM_TOKENS = [
    "8830008372:AAEUpi-Pw0BA2aInmc6BonloWLUZ0nuB8i8"
]

# Admin, Secondary & SAS VIP ALERTS Group
TELEGRAM_CHAT_IDS = [
    "8996427731",          # Admin Chat ID
    "6789591588",          # Secondary Joiner Chat ID
    "-1004399032148"       # SAS VIP ALERTS Group ID
]

IST = pytz.timezone('Asia/Kolkata')
TARGET_PTS = 30.0
SL_PTS = 30.0

# ----------------- TELEGRAM & EMAIL FUNCTIONS -----------------
def send_telegram(message, admin_only=False):
    target_chats = [TELEGRAM_CHAT_IDS[0]] if admin_only else TELEGRAM_CHAT_IDS
    formatted_msg = f"⚡ *SAS LEVEL TRACKER* ⚡\n\n{message}"

    for token in TELEGRAM_TOKENS:
        for cid in target_chats:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": cid,
                "text": formatted_msg,
                "parse_mode": "Markdown"
            }
            try:
                requests.post(url, json=payload, timeout=8)
            except Exception as e:
                print(f"Telegram Error: {e}")

def send_telegram_file(file_path, caption):
    caption_text = f"📊 *SAS LEVEL TRACKER*\n{caption}"
    for token in TELEGRAM_TOKENS:
        for cid in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            try:
                with open(file_path, 'rb') as f:
                    requests.post(
                        url,
                        data={'chat_id': cid, 'caption': caption_text, '
