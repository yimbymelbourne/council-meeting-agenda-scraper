import requests
import re
from pypdf import PdfReader
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import dotenv_values
config = dotenv_values(".env")

def download_pdf(link: str, council_name: str):
  response = requests.get(link)
  with open(f'files/{council_name}_agenda.pdf', 'wb') as f:
      f.write(response.content)
      
       
def read_pdf(council_name: str):
  with open(f'files/{council_name}_agenda.pdf', 'rb') as f:
    reader = PdfReader(f)
    text = ' '.join(page.extract_text() for page in reader.pages)
    return text


def parse_pdf(regex_list, text):
    return {regex: len(re.findall(regex, text)) for regex in regex_list}


def write_email(council_name: str, download_link: str, matches: dict):
    email_body = f"Hello,\n\nThe agenda for {council_name} is now available for download.\n\nPlease click on the link below to download the agenda:\n{download_link}\n\nHere are the matches found in the agenda:\n"
    
    for regex, count in matches.items():
        email_body += f"- {regex}: {count} matches\n"
    
    
def send_email(to, subject, body):
  if int(config['GMAIL_FUNCTIONALITY']) == 1: 
    msg = MIMEMultipart()
    msg['From'] = 'your_email@gmail.com'
    msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(config['GMAIL_ACCOUNT_SEND'], config['GMAIL_PASSWORD'])
    text = msg.as_string()
    server.sendmail(config['GMAIL_ACCOUNT_SEND'], to, text)
    server.quit()
    print(f'Email sent to {to} with subject {subject} and body {body}.')
  else:
    print(f"Email functionality is disabled. Would have sent email to {to} with subject {subject} and body {body}.")
    