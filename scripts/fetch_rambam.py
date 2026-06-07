import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

CALENDAR_URL = "https://www.sefaria.org/api/calendars"
TEXTS_URL = "https://www.sefaria.org/api/texts/{ref}?context=0&pad=0&lang=he"
FONT = "'Frank Ruhl Libre', 'Noto Serif Hebrew', Georgia, serif"

# Each study: search keywords (matched against calendar title.en),
# optional keyword that must also appear (for preferring 3-chapter Rambam),
# Hebrew header shown in the email, and label prefix for each unit.
STUDIES = [
    {
        "keywords": ["Rambam"],
        "prefer_also": "3",
        "he_header": 'רמב"ם יומי',
        "unit_label": "הל'",
    },
    {
        "keywords": ["Tanya"],
        "he_header": "תניא יומי",
        "unit_label": "פס'",
    },
    {
        "keywords": ["Psalms", "Tehillim"],
        "he_header": "תהילים יומי",
        "unit_label": "פס'",
    },
    {
        "keywords": ["Chumash", "Chitas", "Torah Portion", "Parasha"],
        "he_header": "חומש יומי",
        "unit_label": "פס'",
    },
]

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:#f5f0e8;direction:rtl;" dir="rtl">
<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#f5f0e8;direction:rtl;" dir="rtl">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:620px;background:#fffdf7;border-radius:10px;overflow:hidden;font-family:{font};">
        <!-- header -->
        <tr>
          <td align="center" dir="rtl"
              style="background:#2c5f2e;padding:28px 32px 22px;text-align:center;">
            <div style="font-family:{font};font-size:28px;font-weight:700;color:#fff;margin:0;">
              {he_header}
            </div>
            <div style="font-family:{font};font-size:15px;color:#c8e6c9;margin-top:6px;">
              {display_value}
            </div>
          </td>
        </tr>
        <!-- body -->
        <tr>
          <td dir="rtl" style="padding:28px 36px 36px;direction:rtl;">
            {chapters_html}
          </td>
        </tr>
        <!-- footer -->
        <tr>
          <td align="center"
              style="background:#f5f0e8;padding:14px;font-family:{font};font-size:12px;color:#999;">
            מקור: ספריא
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""

_HEB_LETTERS = "אבגדהוזחטיכלמנסעפצקרשת"


def to_hebrew_numeral(n):
    if 1 <= n <= len(_HEB_LETTERS):
        return _HEB_LETTERS[n - 1]
    return str(n)


def get_all_calendar_items():
    resp = requests.get(CALENDAR_URL, timeout=30)
    resp.raise_for_status()
    return resp.json().get("calendar_items", [])


def find_calendar_item(items, study):
    """Return (ref, he_display) for the given study config, or None if not found."""
    keywords = study["keywords"]
    prefer_also = study.get("prefer_also", "")

    # First pass: prefer item that matches a keyword AND the prefer_also string
    if prefer_also:
        for item in items:
            title_en = item.get("title", {}).get("en", "")
            if any(k in title_en for k in keywords) and prefer_also in title_en:
                he_display = item.get("displayValue", {}).get("he") or item.get("displayValue", {}).get("en", item["ref"])
                return item["ref"], he_display

    # Second pass: any matching keyword
    for item in items:
        title_en = item.get("title", {}).get("en", "")
        if any(k in title_en for k in keywords):
            he_display = item.get("displayValue", {}).get("he") or item.get("displayValue", {}).get("en", item["ref"])
            return item["ref"], he_display

    return None


def fetch_text(ref):
    url = TEXTS_URL.format(ref=requests.utils.quote(ref, safe=""))
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("he"):
        raise ValueError(f"No Hebrew text returned for ref: {ref}")
    return data


def flatten_sections(data):
    """Returns list of (title, [unit_html, ...]) tuples."""
    he = data["he"]
    node_title = data.get("heTitle") or data.get("title", "")
    sections_data = data.get("sections", [])

    if he and isinstance(he[0], list):
        result = []
        for i, units in enumerate(he):
            chapter_num = sections_data[0] + i if sections_data else i + 1
            result.append((f"{node_title} — פרק {to_hebrew_numeral(chapter_num)}", units))
        return result
    else:
        chapter_num = sections_data[0] if sections_data else ""
        title = f"{node_title} — פרק {to_hebrew_numeral(chapter_num)}" if chapter_num else node_title
        return [(title, he)]


def clean_unit(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all("sup"):
        tag.decompose()
    return str(soup)


def build_chapters_html(sections, unit_label):
    parts = []
    for title, units in sections:
        rows = []
        for i, raw in enumerate(units, 1):
            text = clean_unit(raw) if raw else ""
            if not text.strip():
                continue
            label = f"{unit_label} {to_hebrew_numeral(i)}" if unit_label else to_hebrew_numeral(i)
            rows.append(
                f'<table width="100%" cellpadding="0" cellspacing="0" border="0" dir="rtl"'
                f' style="margin-bottom:14px;direction:rtl;">'
                f'<tr>'
                f'<td valign="top" dir="rtl" width="42"'
                f' style="font-family:{FONT};font-size:13px;font-weight:700;color:#2c5f2e;'
                f'padding-top:3px;text-align:right;direction:rtl;white-space:nowrap;">'
                f'{label}</td>'
                f'<td valign="top" dir="rtl"'
                f' style="font-family:{FONT};font-size:17px;line-height:1.9;color:#1a1a1a;'
                f'text-align:right;direction:rtl;">'
                f'{text}</td>'
                f'</tr>'
                f'</table>'
            )
        parts.append(
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" dir="rtl"'
            f' style="margin-bottom:32px;direction:rtl;">'
            f'<tr><td dir="rtl" style="direction:rtl;">'
            f'<div style="font-family:{FONT};font-size:20px;font-weight:700;color:#2c5f2e;'
            f'border-bottom:2px solid #2c5f2e;padding-bottom:6px;margin-bottom:18px;'
            f'text-align:right;direction:rtl;">{title}</div>'
            + "".join(rows) +
            f'</td></tr></table>'
        )
    return "\n".join(parts)


def build_plain_fallback(sections, unit_label):
    lines = []
    for title, units in sections:
        lines.append(title)
        lines.append("=" * len(title))
        for i, raw in enumerate(units, 1):
            text = BeautifulSoup(raw, "html.parser").get_text(strip=True) if raw else ""
            if text:
                label = f"{unit_label} {to_hebrew_numeral(i)}" if unit_label else to_hebrew_numeral(i)
                lines.append(f"{label}. {text}")
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


def send_error_email(subject, body, gmail_address, app_password, to_email):
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
        calendar_items = get_all_calendar_items()
    except Exception as exc:
        try:
            send_error_email(
                "שגיאה בלוח השנה היומי",
                f"לא ניתן היה לקבל את לוח השנה מספריא:\n\n{exc}",
                gmail_address, app_password, to_email,
            )
        except Exception:
            pass
        sys.exit(1)

    failed = []
    for study in STUDIES:
        he_header = study["he_header"]
        unit_label = study["unit_label"]
        try:
            result = find_calendar_item(calendar_items, study)
            if result is None:
                print(f"Skipping {he_header}: not found in today's calendar")
                continue
            ref, display_value = result
            data = fetch_text(ref)
            sections = flatten_sections(data)
            chapters_html = build_chapters_html(sections, unit_label)
            html_body = HTML_TEMPLATE.format(
                he_header=he_header,
                display_value=display_value,
                chapters_html=chapters_html,
                font=FONT,
            )
            plain_body = build_plain_fallback(sections, unit_label)
            subject = f"{he_header} — {display_value}"
            send_email(subject, html_body, plain_body, gmail_address, app_password, to_email)
            print(f"Sent: {subject}")
        except Exception as exc:
            print(f"Error sending {he_header}: {exc}", file=sys.stderr)
            failed.append((he_header, str(exc)))

    if failed:
        error_lines = "\n".join(f"{name}: {err}" for name, err in failed)
        try:
            send_error_email(
                "שגיאה בשליחת לימוד יומי",
                f"השגיאות הבאות אירעו:\n\n{error_lines}",
                gmail_address, app_password, to_email,
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
