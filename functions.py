import requests
import re
import os.path

from pypdf import PdfReader
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from _dataclasses import Council, ScraperReturn

from regexes import Regexes, RegexResults, defaults as default_regexes

from dotenv import dotenv_values

config = dotenv_values(".env") if os.path.exists(".env") else {}


def download_pdf(link: str, council_name: str):
    response = requests.get(link)
    with open(f"files/{council_name}_agenda.pdf", "wb") as f:
        f.write(response.content)


def read_pdf(council_name: str):
    with open(f"files/{council_name}_agenda.pdf", "rb") as f:
        reader = PdfReader(f)
        text = " ".join(page.extract_text() for page in reader.pages)
        return text


def parse_pdf(custom_regexes: Regexes | None, text) -> RegexResults:
    regexes = default_regexes

    if custom_regexes is not None:
        regexes = {
            key: custom_regexes[key] + default_regexes[key]
            for key in custom_regexes.keys()
        }

    results = RegexResults()

    if regexes["keyword_matches"]:
        results["keyword_matches"] = {
            regex: len(re.findall(regex, text)) for regex in regexes["keyword_matches"]
        }

    return results


def write_email(
    council: Council, scraper_result: ScraperReturn, parser_results: RegexResults
) -> str:
    email_body = f"Hello,\n\nThe agenda for {council.name} is now available for download.\n\nPlease click on the link below to download the agenda:\n{scraper_result.download_url}\n\nHere are the matches found in the agenda:\n"

    if parser_results["keyword_matches"]:
        email_body += "\nKeyword matches:\n"
        for regex, count in parser_results["keyword_matches"].items():
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
