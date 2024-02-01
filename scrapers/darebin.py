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
  base_url = 'https://www.darebin.vic.gov.au'
  webpage_url = 'https://www.darebin.vic.gov.au/About-Council/Council-structure-and-performance/Council-and-Committee-Meetings/Council-meetings/Meeting-agendas-and-minutes/2024-Council-meeting-agendas-and-minutes'

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

  #all content we are looking for is in the div rte-content
  soup = soup.find("div", class_="rte-content")
  
  #look for the first a tag with the word agenda
  target_a_tag = soup.find('a', href=lambda href: href and 'Agenda' in href)

    # Print the result
  if target_a_tag:
        print('a tag found')
  else:
    print("No 'a' tag with 'agenda' in the href attribute found on the page.")

  href_value = target_a_tag.get('href')
  if href_value:
        download_url = base_url + href_value
        print('download url set')
  else:
        print('link not found.')

    #get the text inside that first name tag - contains both the name of the meeting and the date
  txt_value = target_a_tag.string
  print(txt_value)
  if txt_value:

    #extract the date from txt_value
    match = date_pattern.search(txt_value)

    # Extract the matched date
    if match:
        extracted_date = match.group()
        print("Extracted Date:", extracted_date)
        date = extracted_date
    else:
        print("No date found in the input string.")
    
    #extract the name from text value
  name_ = date_pattern.sub('', txt_value)
  name = name_

  if(name == ''):
    name = 'Council Agenda'

  print('~~~')
  scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)
  
  print(scraper_return.name, scraper_return.date, scraper_return.time, scraper_return.webpage_url, scraper_return.download_url)
  
  return scraper_return

darebin = Council(
  name='darebin',
  scraper=scraper,
)

