import os
import smtplib
import sys
from email.mime.text import MIMEText

import requests

CALENDAR_URL = "https://www.sefaria.org/api/calendars"
TEXTS_URL = "https://www.sefaria.org/api/texts/{ref}?context=0&pad=0&lang=en"


def get_today_rambam_ref():
    resp = requests.get(CALENDAR_URL, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("calendar_items", [])
    # Prefer the 3-chapter version; fall back to any Rambam entry
    for item in items:
        if "Rambam" in item.get("title", {}).get("en", "") and "3" in item.get("title", {}).get("en", ""):
            return item["ref"], item.get("displayValue", {}).get("en", item["ref"])
    for item in items:
        if "Rambam" in item.get("title", {}).get("en", ""):
            return item["ref"], item.get("displayValue", {}).get("en", item["ref"])
    raise ValueError("No Rambam entry found in today's Sefaria calendar")


def fetch_text(ref):
    url = TEXTS_URL.format(ref=requests.utils.quote(ref, safe=""))
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text = data.get("text")
    if not text:
        raise ValueError(f"No English text returned for ref: {ref}")
    return data


def flatten_text(text):
    """Handle both flat list (1 chapter) and nested list (multiple chapters)."""
    if isinstance(text[0], list):
        return text  # already [[ch1_h1, ch1_h2], [ch2_h1, ...], ...]
    return [text]   # wrap single chapter


def build_subject(display_value):
    return f"Daily Rambam — {display_value}"


def build_body(ref, chapters):
    lines = [f"Daily Rambam: {ref}", "=" * (len(ref) + 15), ""]
    for chapter_num, halachot in enumerate(chapters, 1):
        if len(chapters) > 1:
            lines.append(f"Chapter {chapter_num}")
            lines.append("-" * 20)
        for i, halacha in enumerate(halachot, 1):
            text = halacha.strip() if isinstance(halacha, str) else ""
            if text:
                lines.append(f"{i}. {text}")
        lines.append("")
    return "\n".join(lines).strip()


def send_email(subject, body, gmail_address, app_password, to_email):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, app_password)
        server.sendmail(gmail_address, to_email, msg.as_string())


def main():
    gmail_address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_email = os.environ["TO_EMAIL"]

    try:
        ref, display_value = get_today_rambam_ref()
        data = fetch_text(ref)
        chapters = flatten_text(data["text"])
        subject = build_subject(display_value)
        body = build_body(ref, chapters)
        send_email(subject, body, gmail_address, app_password, to_email)
        print(f"Email sent: {subject}")
    except Exception as exc:
        error_subject = "Daily Rambam: fetch failed"
        error_body = f"The daily Rambam script encountered an error:\n\n{type(exc).__name__}: {exc}"
        try:
            send_email(error_subject, error_body, gmail_address, app_password, to_email)
            print(f"Fallback error email sent: {exc}", file=sys.stderr)
        except Exception as mail_exc:
            print(f"Original error: {exc}", file=sys.stderr)
            print(f"Also failed to send fallback email: {mail_exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
