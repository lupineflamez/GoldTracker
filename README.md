# Gold Tracker

A Python-based gold price tracker that checks live gold prices, stores price history, updates a dashboard, and sends email alerts when the price changes.

## Features

- Fetches the latest gold price from a live API
- Tracks previous and current values
- Saves recent price history locally
- Updates a gold-themed dashboard in HTML
- Sends email alerts through Gmail SMTP
- Falls back safely when SMS configuration is missing

## Project structure

- `agent.py` — main bot logic and alert system
- `gold_dashboard.html` — generated dashboard page
- `gold_history.json` — stored historical prices
- `gold_state.json` — last known state and previous price
- `key.env` — local secrets, ignored by GitHub
- `.env.example` — example env file for local use

## Local setup

1. Create a virtual environment:
   - `python -m venv .venv`
2. Activate it:
   - Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
3. Copy `.env.example` to `key.env` and add your real values.
4. Start the tracker:
   - `python agent.py`

## Email configuration

This project is configured to use Gmail SMTP by default.

Set the following values in `key.env`:

```env
ALERT_MODE=email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
SMTP_FROM=your-email@gmail.com
SMTP_TO=your-email@gmail.com
```

> Use a Gmail App Password instead of your normal password.

## SMS configuration

Twilio is optional and not required for the app to run.

If you do not want to pay for SMS, leave the Twilio fields empty and keep `ALERT_MODE=email`.

## Deployment

This app is intended to run as a background worker on a hosting platform such as:

- Render
- Railway
- Fly.io
- a small cloud VM

GitHub itself is for code storage and version control, not for keeping a Python worker running in the background.

## Security

Do not commit real secrets to GitHub.

The project includes a `.gitignore` file to ignore:

- `key.env`
- `.env`
- `.venv/`
- `gold_state.json`
- `gold_history.json`

## Run command

```bash
python agent.py
```

## Notes

The dashboard is generated automatically and can be opened locally in a browser.

This project is best used as a live monitoring tool for gold prices with email alerts, without paying for SMS unless you choose to add Twilio later.
