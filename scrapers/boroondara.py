from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

#fix revised agendas.

import re
date_pattern = re.compile(r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b")
time_pattern = re.compile(r'\b\d{1,2}:\d{2} [apmAPM]+\b')

def scraper() -> ScraperReturn|None:
  base_url = 'https://www.boroondara.vic.gov.au'
  initial_webpage_url = 'https://www.boroondara.vic.gov.au/about-council/councillors-and-meetings/council-and-committee-meetings/past-meeting-minutes-agendas-and-video-recordings'

  chrome_options = Options()
  chrome_options.add_argument("--headless")
  driver = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver, 5)

  #boroondara doesn't have the agenda pdfs on the same page as the list of meetings - need to first find the link to the newest agenda and then read source from that page

  name = None
  date = None
  time = None
  download_url = None

  driver.get(initial_webpage_url)
  # Get the HTML
  output = driver.page_source
  driver.quit()

  # Feed the HTML to BeautifulSoup
  initial_soup = BeautifulSoup(output, 'html.parser')

  node_content = initial_soup.find("div", class_ = 'node__content')
  if node_content:
        first_link = node_content.find('a')
        #print(first_link)

        link_to_agenda = first_link.get('href')
        print(link_to_agenda)
        date_and_time = first_link.find('span', class_ = 'occurrence-date').text
        print("datetime: ", date_and_time)

        if date_and_time:
            date_match = date_pattern.search(date_and_time)
            # Extract the matched date
            if date_match:
                extracted_date = date_match.group()
                print("Extracted Date:", extracted_date)
                date = extracted_date
            else:
                print("No date found in the input string.")

            time_match = time_pattern.search(date_and_time)

            # Extract the matched time
            if time_match:
                extracted_time = time_match.group()
                print("Extracted Date:", extracted_time)
                time = extracted_time
            else:
                print("No time found in the input string.")
        
  else:
    print('failed to find node content')

  #finding and reading current agenda page

  new_url = base_url + link_to_agenda
  print(new_url)

  driver_newpage = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver_newpage, 5)
  driver_newpage.get(new_url)

  # Get the HTML
  output_new = driver_newpage.page_source
  driver_newpage.quit()

  soup = BeautifulSoup(output_new, 'html.parser')

  #first need to find the agenda h3 because the divs of interest are below it

  div = soup.find('div', class_ = 'main')
  if div:
    agenda_h3 = div.find('h3')
    if agenda_h3:
      #print(agenda_h3)
      div_container = agenda_h3.parent.find('div', class_ = 'download-links')
      if div_container:
        #for child in div_container.find_all('span', class_ = 'file-date'):
          #print(child.text)
        #TODO: fix the logic because you can't assume the newest agenda is always on the end!

        n_children = (len(div_container.find_all('a', class_ = 'file-link')))
        latest_agenda = div_container.find_all('a', class_ = 'file-link')[n_children - 1].get('href')
        if(latest_agenda):
           download_url = base_url + latest_agenda
        name_ = div_container.find_all('a', class_ = 'file-link')[n_children - 1].get('data-filename')
        if(name_):
           name = name_
      else:
          print('error cant make div container')
    else:
        print('no agenda h3')

  else:
    print('no div')


  print('~~~')
  scraper_return = ScraperReturn(name, date, time, base_url, download_url)
  
  print(scraper_return.name, scraper_return.date, scraper_return.time, scraper_return.webpage_url, scraper_return.download_url)
  
  return scraper_return

boroondara = Council(
  name='boroondara',
  scraper=scraper,
)

