from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import re

date_pattern = re.compile(
    r"\d{1,2}\s(January|February|March|April|May|June|July|August|September|October|November|December)"
)
time_pattern = re.compile(r"\b\d{1,2}\.\d{2}(?:am|pm)\b")


def scraper() -> ScraperReturn | None:
    base_url = "https://mvcc.vic.gov.au"
    webpage_url = "https://mvcc.vic.gov.au/my-council/council-meetings/"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 5)

    driver.get(webpage_url)

    # Get the HTML
    output = driver.page_source

    driver.quit()

    # Feed the HTML to BeautifulSoup
    soup = BeautifulSoup(output, "html.parser")

    name = None
    date = None
    time = None
    download_url = None

    table = soup.find_all("table")[0].find("tbody")

    if table:
        # print(table)
        counter = 0
        last_meeting = 0
        set = True
        for child in table.find_all("tr"):
            agenda_text = child.find("td", class_="column-2").text
            print(agenda_text)

            if not agenda_text and set:
                last_meeting = counter
                set = False
            else:
                counter = counter + 1
        if set:
            last_meeting = counter
        print(last_meeting)

        last_meeting = table.find_all("tr")[last_meeting - 1]

        datetime = last_meeting.find("td", class_="column-1").text

        print

        match = date_pattern.search(datetime)
        timematch = time_pattern.search(datetime)

        if match:
            extracted_date = match.group()
            print("Extracted Date:", extracted_date)
            date = extracted_date
        else:
            print("no match found for date")

        if timematch:
            extracted_time = timematch.group()
            print("Extracted Time:", extracted_time)
            time = extracted_time
        else:
            print("no match found for time")

        agenda_link = last_meeting.find("td", class_="column-2").find("a").get("href")
        if agenda_link:
            print(agenda_link)
            download_url = agenda_link

    scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

    print(
        scraper_return.name,
        scraper_return.date,
        scraper_return.time,
        scraper_return.webpage_url,
        scraper_return.download_url,
    )

    return scraper_return


mooneevalley = Council(
    name="moonee_valley",
    scraper=scraper,
)
