from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import re
date_pattern = r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"

def scraper() -> ScraperReturn|None:
  base_url = 'https://www.maribyrnong.vic.gov.au/'
  webpage_url = 'https://www.maribyrnong.vic.gov.au/About-us/Council-and-committee-meetings/Agendas-and-minutes'

  chrome_options = Options()
  chrome_options.add_argument("--headless")
  driver = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver, 5)

  driver.get(webpage_url)
  
  # Try to click the accordion header
  try:
    accordion_header = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".accordion-list-item-container:nth-child(1) .item-text")))
    accordion_header.click()
  except Exception as e:
    print(f"Failed to click the accordion header: {e}")

  # Wait for the accordion content to load
  try:
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".meeting-document:nth-child(3) .extension")))
  except Exception as e:
    print(f"Failed to get accordion content: {e}")

  # Get the HTML
  output = driver.page_source

  driver.quit()

  # Feed the HTML to BeautifulSoup
  soup = BeautifulSoup(output, 'html.parser')
  
  name = None
  date = None
  time = None
  download_url = None
  

  div = soup.find('div', class_='meeting-document')
  if div:
    h3 = div.find('h3', string='Agenda')
    if h3:
      link = h3.find_next('a', class_='document ext-pdf')
      if link:
          download_url = base_url + link['href']
      else:
          print('link not found.')
    else: 
      print('h3 not found.')
  else: 
    print('meeting-document not found;\ndownload_url not extracted.')
              
  div = soup.find('div', class_='meeting-time')
  if div:
    time = div.get_text()
    if time:
      time_pattern = r"\d{1,2}:\d{2}\s(?:AM|PM)"
      time = re.search(time_pattern, time).group(0)
  else:
    print('meeting-time not found;\ntime not extracted.')

  
  
  accordion_header = soup.find('div', class_='accordion-list-item-container')
  if accordion_header:
    h2 = accordion_header.find('h2', class_='item-text')
    if h2:
      date = h2.find('span', class_='minutes-date').get_text()
      name = h2.find('span', class_='meeting-type').get_text()
      print(date)
      print(name)
  else:
    print('accordion-list-item-container not found.')
  
  scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)
  
  print(scraper_return.name, scraper_return.date, scraper_return.time, scraper_return.webpage_url, scraper_return.download_url)
  
  return scraper_return

maribyrnong = Council(
  name='Maribyrnong',
  scraper=scraper,
)

