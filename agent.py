import base64
import datetime as dt
import json
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any


class DotEnvLoader:
    """Read KEY=VALUE pairs from a .env file and populate os.environ."""

    def __init__(self, dotenv_path: str = "key.env", override: bool = False):
        self.dotenv_path = dotenv_path
        self.override = override

    def parse_line(self, raw_line: str):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            return None
        if "=" not in line:
            return None

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        return key, value

    def load(self, dotenv_path: str | None = None, override: bool | None = None):
        path = Path(dotenv_path or self.dotenv_path)
        if not path.exists():
            return False

        if override is None:
            override = self.override

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            parsed = self.parse_line(raw_line)
            if parsed is None:
                continue

            key, value = parsed
            if key in os.environ and not override:
                continue

            os.environ[key] = value

        return True

    def __call__(self, dotenv_path: str | None = None, override: bool | None = None):
        return self.load(dotenv_path=dotenv_path, override=override)


load_dotenv = DotEnvLoader(dotenv_path="key.env")
STATE_FILE = Path("gold_state.json")
HISTORY_FILE = Path("gold_history.json")
DASHBOARD_FILE = Path("gold_dashboard.html")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fetch_gold_price() -> float:
    """Fetch the current gold price in USD per ounce from a public API."""
    urls = [
        "https://api.gold-api.com/price/XAU/USD",
        "https://api.coinbase.com/v2/prices/XAU-USD/spot",
        "https://api.metals.live/v1/price/all",
        "https://api.metals.live/v1/price",
    ]

    last_error: Exception | None = None
    for url in urls:
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "GoldTrackerAgent/1.0"},
            )
            try:
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=20, context=context) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(request, timeout=20, context=context) as response:
                    payload = json.loads(response.read().decode("utf-8"))

            gold_price = extract_gold_price(payload)
            if gold_price is not None:
                return float(gold_price)
        except (urllib.error.URLError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise RuntimeError(f"Unable to fetch gold price: {last_error}")
    raise RuntimeError("No supported gold price data was returned by the API.")


def extract_gold_price(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for key in ("gold", "XAU", "XAUUSD", "price", "amount", "value", "exchangeRate"):
            if key in payload:
                value = payload[key]
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except ValueError:
                        pass
                if isinstance(value, dict):
                    nested = extract_gold_price(value)
                    if nested is not None:
                        return nested

        for value in payload.values():
            if isinstance(value, (dict, list)):
                nested = extract_gold_price(value)
                if nested is not None:
                    return nested

    if isinstance(payload, list):
        for item in payload:
            price = extract_gold_price(item)
            if price is not None:
                return price

    return None


def read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_state(data: dict[str, Any]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def get_previous_price() -> float | None:
    data = read_state()
    price = data.get("previous_price")
    return float(price) if price is not None else None


def save_previous_price(price: float) -> None:
    state = read_state()
    state["previous_price"] = price
    state["updated_at"] = utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
    save_state(state)


def build_status_message(current_price: float, previous_price: float | None) -> str:
    if previous_price is None:
        return (
            f"Gold alert: ${current_price:.2f} per ounce. "
            "This is your baseline price and no previous reading is available yet."
        )

    change = current_price - previous_price
    percent_change = (change / previous_price) * 100 if previous_price else 0.0
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged"

    if direction == "unchanged":
        return (
            f"Gold status: ${current_price:.2f} per ounce. "
            f"No change from the previous price of ${previous_price:.2f}."
        )

    return (
        f"Gold status: ${current_price:.2f} per ounce. "
        f"It is {direction} from ${previous_price:.2f} "
        f"by ${abs(change):.2f} ({percent_change:+.2f}%)."
    )


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def save_history(history: list[dict[str, Any]]) -> None:
    with HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(history, file, indent=2)


def append_price_history(price: float) -> None:
    history = load_history()
    snapshot = {
        "timestamp": utc_now().isoformat(),
        "price": float(price),
    }
    history.append(snapshot)
    if len(history) > 500:
        history = history[-500:]
    save_history(history)
    write_dashboard(history)


def write_dashboard(history: list[dict[str, Any]]) -> None:
    if not history:
        html = "<html><body><h1>Gold Dashboard</h1><p>No price data yet.</p></body></html>"
        DASHBOARD_FILE.write_text(html, encoding="utf-8")
        return

    rows = "".join(
        f"<tr><td>{item['timestamp']}</td><td>${item['price']:.2f}</td></tr>"
        for item in history[-20:]
    )
    latest = history[-1]["price"]
    first = history[0]["price"]
    previous = history[-2]["price"] if len(history) >= 2 else history[0]["price"]
    change = latest - first
    change_text = f"{change:+.2f}" if change else "+0.00"
    delta_from_previous = latest - previous
    delta_from_previous_text = f"{delta_from_previous:+.2f}" if delta_from_previous else "+0.00"
    last_updated = history[-1]["timestamp"]

    html = f"""
    <!DOCTYPE html>
    <html lang=\"en\">
    <head>
        <meta charset=\"UTF-8\" />
        <title>Gold Price Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; background: linear-gradient(135deg, #f9f4e8, #f1efe7); margin: 30px; color: #1f2937; }}
            h1 {{ color: #7a5a13; letter-spacing: 0.04em; margin: 0 0 12px; }}
            .gold-banner {{
                display: inline-block;
                background: linear-gradient(135deg, #f5d76d, #d4a52d, #f7e7a4);
                color: #3b2c0a;
                padding: 8px 14px;
                border-radius: 999px;
                font-weight: bold;
                letter-spacing: 0.08em;
                margin-bottom: 20px;
                box-shadow: 0 4px 10px rgba(154, 116, 18, 0.25);
            }}
            .card {{ background: rgba(255,255,255,0.9); border-radius: 14px; padding: 24px; box-shadow: 0 8px 25px rgba(98, 76, 14, 0.12); max-width: 980px; border: 1px solid rgba(202, 170, 71, 0.25); }}
            .meta {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
            .badge {{ display: inline-block; background: #fff9e6; color: #7a5a13; padding: 10px 14px; border-radius: 999px; font-weight: bold; border: 1px solid rgba(183, 137, 27, 0.25); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border-bottom: 1px solid #e7dcc0; padding: 12px 10px; text-align: left; }}
            th {{ background: #f7f2e4; color: #6b4a00; }}
            .muted {{ color: #7a5a13; font-size: 0.95em; }}
        </style>
    </head>
    <body>
        <div class=\"card\">
            <div class=\"gold-banner\">▇▇ Gold Tracker ▇▇</div>
            <h1>Gold Tracker Dashboard</h1>
            <div class=\"meta\">
                <div class=\"badge\">Latest price: ${latest:.2f}</div>
                <div class=\"badge\">Previous price: ${previous:.2f}</div>
                <div class=\"badge\">Change since first reading: ${change_text}</div>
                <div class=\"badge\">Last price change: ${delta_from_previous_text}</div>
                <div class=\"badge muted\">Last updated: {last_updated}</div>
            </div>
            <table>
                <thead>
                    <tr><th>Timestamp</th><th>Price</th></tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    DASHBOARD_FILE.write_text(html, encoding="utf-8")


def build_daily_summary_message() -> str:
    history = load_history()
    if len(history) < 2:
        return "Gold daily summary: not enough price history yet to compare a full day."

    start_of_day = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    filtered = [
        item for item in history
        if dt.datetime.fromisoformat(item["timestamp"]) >= start_of_day
    ]

    if len(filtered) < 2:
        return "Gold daily summary: only a partial day of data is available so far."

    first_price = filtered[0]["price"]
    latest_price = filtered[-1]["price"]
    change = latest_price - first_price
    percent_change = (change / first_price) * 100 if first_price else 0.0
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged"

    return (
        f"Daily gold summary: ${latest_price:.2f} per ounce. "
        f"This is {direction} from ${first_price:.2f} by ${abs(change):.2f} ({percent_change:+.2f}%)."
    )


def should_send_daily_summary() -> bool:
    state = read_state()
    today = dt.date.today().isoformat()
    return state.get("daily_summary_date") != today


def send_daily_summary_if_needed() -> None:
    if not should_send_daily_summary():
        return

    summary_message = build_daily_summary_message()
    send_alert(summary_message)
    state = read_state()
    state["daily_summary_date"] = dt.date.today().isoformat()
    save_state(state)


def send_startup_sms() -> None:
    price = fetch_gold_price()
    state = read_state()
    if state.get("boot_alert_sent"):
        return

    send_alert(f"Gold tracker started. Current gold price: ${price:.2f} per ounce.")
    state["boot_alert_sent"] = True
    save_state(state)


def has_email_config() -> bool:
    return all(
        os.getenv(name)
        for name in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO")
    )


def has_sms_config() -> bool:
    return all(
        os.getenv(name)
        for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_TO")
    )


def send_email(message: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM")
    to_email = os.getenv("SMTP_TO")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "y"}

    missing = [
        name for name, value in {
            "SMTP_USER": smtp_user,
            "SMTP_PASSWORD": smtp_password,
            "SMTP_FROM": from_email,
            "SMTP_TO": to_email,
        }.items() if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing email SMTP env vars: " + ", ".join(missing)
            + ". Update your key.env file before sending email alerts."
        )

    gold_header = "▇▇▇ GOLD ALERT ▇▇▇"
    email = EmailMessage()
    email["Subject"] = f"{gold_header} - {message[:80]}"
    email["From"] = from_email
    email["To"] = to_email
    email.set_content(f"{gold_header}\n\n{message}\n\n🟡 Gold Tracker\nLast updated: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if use_tls:
            server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(email)

    print("Email sent successfully.")


def send_sms(message: str) -> None:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM")
    to_number = os.getenv("TWILIO_TO")

    missing = [
        name for name, value in {
            "TWILIO_ACCOUNT_SID": account_sid,
            "TWILIO_AUTH_TOKEN": auth_token,
            "TWILIO_FROM": from_number,
            "TWILIO_TO": to_number,
        }.items() if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Twilio env vars: " + ", ".join(missing)
            + ". Update your key.env file before sending SMS alerts."
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = urllib.parse.urlencode({"To": to_number, "From": from_number, "Body": message}).encode("utf-8")
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("utf-8")

    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Authorization", f"Basic {auth}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8")

    print(f"SMS sent successfully: {response_body[:200]}")


def send_alert(message: str) -> None:
    alert_mode = os.getenv("ALERT_MODE", "email").lower()

    if alert_mode == "sms":
        if not has_sms_config():
            if has_email_config():
                print("Twilio SMS is not configured; falling back to email alerts.")
                send_email(message)
                return
            raise RuntimeError(
                "SMS mode was selected but Twilio values are missing. Add TWILIO_* values or set ALERT_MODE=email."
            )
        send_sms(message)
        return

    if not has_email_config():
        if has_sms_config() and alert_mode != "email":
            print("Email is not configured; falling back to SMS alerts.")
            send_sms(message)
            return
        raise RuntimeError(
            "No alert delivery method is configured. Add SMTP_* values or set ALERT_MODE=sms with Twilio credentials."
        )

    send_email(message)


def run_check() -> None:
    current_price = fetch_gold_price()
    previous_price = get_previous_price()
    status_message = build_status_message(current_price, previous_price)
    print(status_message)
    send_alert(status_message)
    save_previous_price(current_price)
    append_price_history(current_price)
    send_daily_summary_if_needed()


def main() -> None:
    load_dotenv.load(dotenv_path="key.env")
    print("Gold tracker started. Checking every 30 minutes.")

    try:
        send_startup_sms()
    except Exception as exc:
        print(f"Startup SMS failed: {exc}")

    while True:
        try:
            run_check()
            time.sleep(30 * 60)
        except KeyboardInterrupt:
            print("Gold tracker stopped by user.")
            break
        except Exception as exc:
            print(f"An error occurred: {exc}")
            time.sleep(60)


if __name__ == "__main__":
    main()