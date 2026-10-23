name: Nifty Trading Bot Runner

on:
  schedule:
    # 03:15 UTC = 08:45 AM IST (Starts before market opens)
    - cron: '15 3 * * 1-5'
  workflow_dispatch: # Manual start button

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 420

    steps:
      - name: Check out Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Dependencies
        run: |
          pip install yfinance pandas ta requests reportlab pytz

      - name: Run Scalper Bot
        run: |
          python scalper.py
