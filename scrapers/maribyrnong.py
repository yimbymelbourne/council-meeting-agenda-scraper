from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from type_module import Council

def scraper() -> str|None:
  base_url = 'https://www.maribyrnong.vic.gov.au/'
  agenda_url = 'https://www.maribyrnong.vic.gov.au/About-us/Council-and-committee-meetings/Agendas-and-minutes'

  chrome_options = Options()
  chrome_options.add_argument("--headless")
  driver = webdriver.Chrome(options=chrome_options)
  wait = WebDriverWait(driver, 5)

  driver.get(agenda_url)
  
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

  output = driver.page_source

  driver.quit()

  soup = BeautifulSoup(output, 'html.parser')
  
  download_link = None

  div = soup.find('div', class_='meeting-document')
  if div:
    h3 = div.find('h3', string='Agenda')
    if h3:
        link = h3.find_next('a', class_='document ext-pdf')
        if link:
            download_link = base_url + link['href']
  else: 
    print('No div found.')
  
  return download_link


maribyrnong: Council = {
  'council': 'Maribyrnong',
  'regex_list': ['dwellings', 'heritage'],
  'scraper': scraper,
}