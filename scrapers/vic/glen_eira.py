from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

# fix revised agendas.

import re

date_pattern = re.compile(
    r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
)
time_pattern = re.compile(r"\b\d{1,2}\.\d{2}(?:am|pm)\b")



def scraper() -> ScraperReturn | None:
    base_url = "https://www.gleneira.vic.gov.au"
    initial_webpage_url = "https://www.gleneira.vic.gov.au/about-council/meetings-and-agendas/council-agendas-and-minutes"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 5)

    # boroondara doesn't have the agenda pdfs on the same page as the list of meetings - need to first find the link to the newest agenda and then read source from that page

    name = None
    date = None
    time = None
    download_url = None

    driver.get(initial_webpage_url)
    # Get the HTML
    output = driver.page_source
    driver.quit()

    # Feed the HTML to BeautifulSoup
    initial_soup = BeautifulSoup(output, "html.parser")

    listing_div = initial_soup.find('div', class_ = 'listing__list')
    if listing_div:
        print('found div')
        first_meeting = listing_div.find('a', class_ = 'listing')
        if first_meeting:
            print(first_meeting.get('href'))
            link_to_agenda = first_meeting.get('href')

    new_url = base_url + link_to_agenda
    print(new_url)

    driver_newpage = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver_newpage, 5)
    driver_newpage.get(new_url)

    # Get the HTML
    output_new = driver_newpage.page_source
    driver_newpage.quit()

    soup = BeautifulSoup(output_new, "html.parser")

    header = soup.find('header')
    if header:
        meeting_title = header.find('p', class_='h5').text
        if meeting_title:
            name = meeting_title
        meeting_datetime = header.find('span', class_= 'page-title__text' ).text
        if meeting_datetime:
            date_match = date_pattern.search(meeting_datetime)
            # Extract the matched date
            if date_match:
                extracted_date = date_match.group()
                print("Extracted Date:", extracted_date)
                date = extracted_date
            else:
                print("No date found in the input string.")

        introduction = soup.find('div', id = 'introduction')
        if introduction:
            print(introduction.text)
            time_match = time_pattern.search(introduction.text)
            
            # Extract the matched time
            if time_match:
                extracted_time = time_match.group()
                print("Extracted Date:", extracted_time)
                time = extracted_time
            else:
                print("No time found in the input string.")
        else:
            print('no introduction div found')
    resource_div = soup.find('div', class_='layout__main-content')
    if resource_div:
        mb_5 = soup.find('section', class_ = 'mb-5')
        if mb_5:
            resource_link = mb_5.find('a', class_ = 'resource__link')
            if resource_link:
                download_url = resource_link.get('href')
            else:
                print('couldnt find link')
        else:
            print('cant find section')
    else:
        print('couldnt locate resource div')

    scraper_return = ScraperReturn(name, date, time, base_url, download_url)

    print(
        scraper_return.name,
        scraper_return.date,
        scraper_return.time,
        scraper_return.webpage_url,
        scraper_return.download_url,
    )

    return scraper_return


glen_eira = Council(
    name= "glen_eira",
    scraper=scraper,
)
