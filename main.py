import os.path

from functions import download_pdf, read_pdf, parse_pdf, write_email, send_email
import database as db

from dotenv import dotenv_values
config = dotenv_values(".env")

# Web scraping
from scrapers.index import councils

def processor(council: dict):
  council_name, regex_list = council['council'], council['regex_list']
  
  print(f'Running {council_name} scraper...')
  download_link = council['scraper']()

  if not download_link:
    print(f'No link found for {council_name}.')
    return
  if db.check_link(download_link):
    print(f'Link already scraped for {council_name}.')
    return
  
  print('Link scraped! Downloading PDF...')
  download_pdf(download_link, council_name)
  
  print('PDF downloaded! Reading PDF...')
  text = read_pdf(council_name)
  
  print('PDF read! Parsing PDF...')
  matches = parse_pdf(regex_list, text)  
  
  print('PDF parsed! Inserting into database...')
  db.insert(council_name, download_link, matches)
  print('Database updated!')
  
  print('Sending email...')
  
  email_body = write_email(council_name, download_link, matches)

  send_email(config['GMAIL_ACCOUNT_RECEIVE'], 
              f'New agenda: {council_name}', 
              email_body)
  
  print(f'Finished with {council_name}.')  
  

def main():
  print(config['GMAIL_FUNCTIONALITY'], 
        type(config['GMAIL_FUNCTIONALITY']), 
        type(int(config['GMAIL_FUNCTIONALITY'])),
        int(config['GMAIL_FUNCTIONALITY']) == 1
  )
  if not os.path.exists('./agendas.db'):
    db.init()
  
  for council in councils:
    processor(council)
  
  
if __name__ == '__main__':
  main()