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


# Sending emails
def send_email(to, subject, body):
  if config['GMAIL_FUNCTIONALITY'] == 1: 
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
  else:
    print(f"Email functionality is disabled. Would have sent email to {to} with subject {subject} and body {body}.")
    