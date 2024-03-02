import requests
import re
import os.path

import fitz
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from base import ScraperReturn

from dotenv import dotenv_values


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


def parse_pdf(regexes: list[re.Pattern], text) -> dict[str, int] | None:
    return {regex: len(re.findall(regex, text)) for regex in regexes}


def write_email(
    council_name: str,
    scraper_result: ScraperReturn,
    parser_results: dict[str, int] = None,
) -> str:
    email_body = f"Hello,\n\nThe agenda for the {scraper_result.date} {council_name} meeting is now available for download.\n\nPlease click on the link below to download the agenda:\n{scraper_result.download_url}\n\n"

    if parser_results["keyword_matches"]:
        email_body += "Here are the matches found in the agenda:\n"
        email_body += "\nKeyword matches:\n"
        for regex, count in parser_results.items():
            email_body += f"- {regex}: {count} matches\n"

    email_body += "\n\nThank you,\nYour friendly neighborhood agenda scraper"

    return email_body


def send_email(to, subject, body):
    if int(config["GMAIL_FUNCTIONALITY"]) == 1:
        msg = MIMEMultipart()
        msg["From"] = "your_email@gmail.com"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(config["GMAIL_ACCOUNT_SEND"], config["GMAIL_PASSWORD"])
        text = msg.as_string()
        server.sendmail(config["GMAIL_ACCOUNT_SEND"], to, text)
        server.quit()
        print(f"Email sent to {to} with subject {subject} and body {body}.")
    else:
        print(
            f"Email functionality is disabled. Would have sent email to {to} with subject {subject} and body {body}."
        )
