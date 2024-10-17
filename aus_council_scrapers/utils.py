import os.path
import re
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import fitz
import pytz
import requests
from dotenv import dotenv_values

from aus_council_scrapers.constants import TIMEZONES_BY_STATE
from aus_council_scrapers.data import ScraperResult

config = dotenv_values(".env") if os.path.exists(".env") else {}


def download_pdf(link: str, council_name: str):
    response = requests.get(link)
    os.makedirs("files", exist_ok=True)
    with open(f"files/{council_name}_latest.pdf", "wb") as f:
        f.write(response.content)


def read_pdf(council_name: str):
    doc = fitz.open(f"files/{council_name}_latest.pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text


KeywordCounts = dict[str, int]


def extract_keywords(regexes: list[str], text) -> tuple[KeywordCounts, int]:
    cleaned = re.sub(r"\s+", " ", text)
    cleaned = re.sub(r"\t", " ", cleaned)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    cleaned = cleaned.lower()
    keywords = {regex: len(re.findall(regex, cleaned)) for regex in regexes}
    wordcount = len(cleaned.split(" "))
    return keywords, wordcount


def write_email(
    council_name: str,
    scraper_result: ScraperResult.CouncilMeetingNotice,
    parser_results: Optional[dict[str, int]] = None,
) -> str:
    email_body = f"Hello,\n\nThe agenda for the {scraper_result.datetime.date} " \
                 f"{council_name} meeting is now available for download.\n\n" \
                 f"Please click on the link below to download the agenda:\n" \
                 f"{scraper_result.download_url}\n\n"

    if parser_results and len(parser_results) > 0:
        email_body += "Here are the matches found in the agenda:\n"
        email_body += "\nKeyword matches:\n"
        for regex, count in parser_results.items():
            email_body += f"- {regex}: {count} matches\n"

    email_body += "\n\nThank you,\nYour friendly neighborhood agenda scraper"

    return email_body


def send_email(to, subject, body):
    sender_email = config["GMAIL_ACCOUNT_SEND"]
    password = config["GMAIL_PASSWORD"]
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender_email, password)
    text = msg.as_string()
    server.sendmail(sender_email, to, text)
    server.quit()


def format_date_for_message(date: datetime.date):
    current_year = datetime.datetime.today().year
    if date.year == current_year:
        return date.strftime("%d %b")

    return date.strftime("%d %b %Y")
