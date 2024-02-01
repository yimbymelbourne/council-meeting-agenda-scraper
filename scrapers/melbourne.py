from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import re
date_pattern = re.compile(r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b")
time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"

def scraper() -> ScraperReturn|None:
  base_url = 'https://www.melbourne.vic.gov.au'
  webpage_url = 'https://www.melbourne.vic.gov.au/pages/meetings-finder.aspx?type=41&attach=False'

  chrome_options = Options()
  chrome_options.add_argument("--headless")
  driver = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver, 5)

  driver.get(webpage_url)
  
  # Get the HTML
  output = driver.page_source

  driver.quit()

  # Feed the HTML to BeautifulSoup
  soup = BeautifulSoup(output, 'html.parser')
  
  name = None
  date = None
  time = None
  download_url = None
  
  agenda_link = None

  meeting_results = soup.find('div', id = 'meetingResults')
  if meeting_results:
        result = meeting_results.find('div', class_ = 'result')
        if result:
            link = result.find('a')
            if link:
                agenda_link = link.get('href')
                namedate = link.text

                match = date_pattern.search(namedate)

                if match:
                    extracted_date = match.group()
                    print("Extracted Date:", extracted_date)
                    date = extracted_date

                name_string = namedate.replace(date, '')
                if name_string:
                    name = name_string
            

  driver = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver, 5)

  driver.get(agenda_link)
  
  # Get the HTML
  new_output = driver.page_source

  driver.quit()

  newsoup = BeautifulSoup(new_output, 'html.parser')

  agenda_div = newsoup.find_all('div', class_ = 'download-container')[1]
  if agenda_div:
      print(agenda_div)
      pdf_link = agenda_div.find('a', class_ = 'download-link').get('href')
      if pdf_link:
          download_url = base_url + pdf_link

  print('~~~')
  scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)
  
  print(scraper_return.name, scraper_return.date, scraper_return.time, scraper_return.webpage_url, scraper_return.download_url)
  
  return scraper_return

melbourne = Council(
  name='melbourne',
  scraper=scraper,
)