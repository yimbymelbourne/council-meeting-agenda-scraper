from functions import download_pdf, read_pdf, parse_pdf, send_email

from dotenv import dotenv_values
config = dotenv_values(".env")

# Web scraping
from scrapers.maribyrnong import maribyrnong as maribyrnong

def processor(council: dict):
  council_name, regex_list = council['council'], council['regex_list']
  
  print(f'Running {council_name} scraper...')
  download_link = council['scraper']
  print(download_link)
  
  print('Link scraped! Downloading PDF...')
  download_pdf(download_link, council_name)
  
  print('PDF downloaded! Reading PDF...')
  text = read_pdf(council_name)
  regex_list = ['dwellings', 'heritage']
  
  print('PDF read! Parsing PDF...')
  matches = parse_pdf(regex_list, text)  
  print(matches)
  
  print('PDF parsed! Sending email...')
  if config['GMAIL_FUNCTIONALITY'] == 1: 
    send_email(config['GMAIL_ACCOUNT_RECEIVE'], f'New agenda: {council_name}', str(matches))
    print(f'Email sent!')
  else:
    print(f"Email functionality is disabled.")
    
  print(f'Finished with {council_name}.')  
  

def main():
  processor(maribyrnong)
  
if __name__ == '__main__':
  main()