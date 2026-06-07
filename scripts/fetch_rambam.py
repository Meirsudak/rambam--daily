import os
import smtplib
import sys
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

URL = "https://www.chabad.org/dailystudy/rambam_cdo/rambamChapters/3"


def fetch_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    session = requests.Session()
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_rambam(html):
    soup = BeautifulSoup(html, "html.parser")

    titles = [h2.get_text(strip=True) for h2 in soup.select("h2.rambam_h2")]
    if not titles:
        raise ValueError("No chapter titles found — page structure may have changed")

    # Remove Hebrew spans before extracting verse text
    for hebrew in soup.select("span[lang='he']"):
        hebrew.decompose()

    halachot = [span.get_text(strip=True) for span in soup.select("span.co_verse")]
    if not halachot:
        raise ValueError("No halacha verses found — page structure may have changed")

    return {"titles": titles, "halachot": halachot}


def build_subject(titles):
    return " | ".join(titles)


def build_body(titles, halachot):
    lines = []
    for title in titles:
        lines.append(title)
        lines.append("=" * len(title))
    lines.append("")
    for i, text in enumerate(halachot, 1):
        lines.append(f"{i}. {text}")
    return "\n".join(lines)


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
        html = fetch_page(URL)
        data = parse_rambam(html)
        subject = build_subject(data["titles"])
        body = build_body(data["titles"], data["halachot"])
        send_email(subject, body, gmail_address, app_password, to_email)
        print(f"Email sent: {subject}")
    except Exception as exc:
        error_subject = "Rambam Daily: fetch failed"
        error_body = (
            f"The daily Rambam script encountered an error:\n\n{type(exc).__name__}: {exc}"
        )
        try:
            send_email(error_subject, error_body, gmail_address, app_password, to_email)
            print(f"Fallback error email sent: {exc}", file=sys.stderr)
        except Exception as mail_exc:
            print(f"Original error: {exc}", file=sys.stderr)
            print(f"Also failed to send fallback email: {mail_exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
