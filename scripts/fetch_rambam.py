import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

CALENDAR_URL = "https://www.sefaria.org/api/calendars"
TEXTS_URL = "https://www.sefaria.org/api/texts/{ref}?context=0&pad=0&lang=he"

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap" rel="stylesheet">
<style>
  body {{
    margin: 0;
    padding: 0;
    background: #f5f0e8;
    font-family: 'Frank Ruhl Libre', 'David', 'Times New Roman', serif;
    direction: rtl;
    color: #1a1a1a;
  }}
  .wrapper {{
    max-width: 640px;
    margin: 32px auto;
    background: #fffdf7;
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.10);
    overflow: hidden;
  }}
  .header {{
    background: #2c5f2e;
    color: #fff;
    padding: 28px 32px 20px;
    text-align: center;
  }}
  .header h1 {{
    margin: 0;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}
  .header .date {{
    margin: 6px 0 0;
    font-size: 14px;
    opacity: 0.85;
  }}
  .body {{
    padding: 28px 36px 36px;
  }}
  .chapter {{
    margin-bottom: 32px;
  }}
  .chapter-title {{
    font-size: 20px;
    font-weight: 700;
    color: #2c5f2e;
    border-bottom: 2px solid #2c5f2e;
    padding-bottom: 6px;
    margin-bottom: 16px;
  }}
  .halacha {{
    display: flex;
    gap: 10px;
    margin-bottom: 14px;
    line-height: 1.85;
    font-size: 17px;
    align-items: flex-start;
  }}
  .halacha-num {{
    min-width: 28px;
    font-weight: 700;
    color: #2c5f2e;
    font-size: 14px;
    padding-top: 4px;
    flex-shrink: 0;
    text-align: center;
  }}
  .halacha-text {{
    flex: 1;
  }}
  .footer {{
    text-align: center;
    padding: 16px;
    font-size: 12px;
    color: #999;
    background: #f5f0e8;
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>רמב"ם יומי</h1>
    <div class="date">{display_value}</div>
  </div>
  <div class="body">
    {chapters_html}
  </div>
  <div class="footer">מקור: ספריא</div>
</div>
</body>
</html>
"""


def get_today_rambam_ref():
    resp = requests.get(CALENDAR_URL, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("calendar_items", [])
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
    if not data.get("he"):
        raise ValueError(f"No Hebrew text returned for ref: {ref}")
    return data


def flatten_sections(data):
    """
    Returns list of (title, [halacha_html, ...]) tuples.
    Handles single chapter (flat list) and multi-chapter (nested list).
    """
    he = data["he"]
    node_title = data.get("title", "")

    if he and isinstance(he[0], list):
        # Multi-chapter: he = [[ch1_h1, ch1_h2], [ch2_h1], ...]
        sections_data = data.get("sections", [])
        result = []
        for i, chapter_halachot in enumerate(he):
            chapter_num = sections_data[0] + i if sections_data else i + 1
            result.append((f"{node_title} פרק {chapter_num}", chapter_halachot))
        return result
    else:
        sections_data = data.get("sections", [])
        chapter_num = sections_data[0] if sections_data else ""
        title = f"{node_title} פרק {chapter_num}" if chapter_num else node_title
        return [(title, he)]


def clean_halacha(raw_html):
    """Strip tags but preserve inner HTML for rendering."""
    # Remove footnote markers (sup tags) that clutter reading
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all("sup"):
        tag.decompose()
    return str(soup)


def build_chapters_html(sections):
    parts = []
    for title, halachot in sections:
        halacha_items = []
        for i, raw in enumerate(halachot, 1):
            text = clean_halacha(raw) if raw else ""
            if not text.strip():
                continue
            halacha_items.append(
                f'<div class="halacha">'
                f'<div class="halacha-num">{i}</div>'
                f'<div class="halacha-text">{text}</div>'
                f'</div>'
            )
        parts.append(
            f'<div class="chapter">'
            f'<div class="chapter-title">{title}</div>'
            + "".join(halacha_items) +
            f'</div>'
        )
    return "\n".join(parts)


def build_plain_fallback(sections):
    lines = []
    for title, halachot in sections:
        lines.append(title)
        lines.append("=" * len(title))
        for i, raw in enumerate(halachot, 1):
            text = BeautifulSoup(raw, "html.parser").get_text(strip=True) if raw else ""
            if text:
                lines.append(f"{i}. {text}")
        lines.append("")
    return "\n".join(lines).strip()


def send_email(subject, html_body, plain_body, gmail_address, app_password, to_email):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = to_email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
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
        sections = flatten_sections(data)
        chapters_html = build_chapters_html(sections)
        html_body = HTML_TEMPLATE.format(
            display_value=display_value,
            chapters_html=chapters_html,
        )
        plain_body = build_plain_fallback(sections)
        subject = f'רמב"ם יומי — {display_value}'
        send_email(subject, html_body, plain_body, gmail_address, app_password, to_email)
        print(f"Email sent: {subject}")
    except Exception as exc:
        error_subject = "Daily Rambam: fetch failed"
        error_body = f"The daily Rambam script encountered an error:\n\n{type(exc).__name__}: {exc}"
        try:
            plain_msg = MIMEText(error_body, "plain", "utf-8")
            plain_msg["Subject"] = error_subject
            plain_msg["From"] = gmail_address
            plain_msg["To"] = to_email
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_address, app_password)
                server.sendmail(gmail_address, to_email, plain_msg.as_string())
            print(f"Fallback error email sent: {exc}", file=sys.stderr)
        except Exception as mail_exc:
            print(f"Original error: {exc}", file=sys.stderr)
            print(f"Also failed to send fallback email: {mail_exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
