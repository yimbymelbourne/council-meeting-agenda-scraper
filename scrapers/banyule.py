from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import re

date_pattern = re.compile(
    r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
)
time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"


def scraper() -> ScraperReturn | None:
    base_url = "https://www.banyule.vic.gov.au"
    webpage_url = "https://www.banyule.vic.gov.au/About-us/Councillors-and-Council-meetings/Council-meetings/Council-meeting-agendas-and-minutes"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 25)

    driver.get(webpage_url)

    try:
        # Find all buttons with the class "minutes-trigger"
        buttons_to_click = driver.find_elements(By.CLASS_NAME, ".minutes-trigger")

        # Click on each button
        for button in buttons_to_click:
            button.click()

            # Wait for the content to load (adjust the timeout as needed)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, ".accordion-item-body .initialised")
                )
            )

        # Read the entire page content
        page_content = driver.page_source
        print("Page content:", page_content)

    finally:
        # Close the browser
        driver.quit()

    # Feed the HTML to BeautifulSoup
    soup = BeautifulSoup(output, "html.parser")

    name = None
    date = None
    time = None
    download_url = None

    main_div = soup.find("div", class_="main-inner-container")
    if main_div:
        grid_div = main_div.find("div", class_="grid")
        if grid_div:
            n_children = len(
                grid_div.find_all("div", class_="accordion-list-item-container")
            )
            # print(n_children)
            counter = 0
            found_last_meeting = False
            while not found_last_meeting:
                current = grid_div.find_all(
                    "div", class_="accordion-list-item-container"
                )[counter]
                # print(current)
                # time_ = current.find_all('div', class_ ='meeting-time')

                counter = counter + 1

        else:
            print("no grid div found")
    else:
        print("no main div found")

    print("~~~")
    scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

    print(
        scraper_return.name,
        scraper_return.date,
        scraper_return.time,
        scraper_return.webpage_url,
        scraper_return.download_url,
    )

    return scraper_return


banyule = Council(
    name="banyule",
    scraper=scraper,
)
