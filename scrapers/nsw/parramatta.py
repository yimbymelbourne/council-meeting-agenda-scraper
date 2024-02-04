from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import requests
import re

_BUSINESS_PAPER_URL = "https://businesspapers.parracity.nsw.gov.au"
_BUSINESS_PAPER_ROW_SELECTOR = "#grdMenu tbody > tr"
_date_re = re.compile(r"\b(\d{1,2})\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s(\d{4})")
_time_re = re.compile(r"\b(\d{1,2}.\d{2})(am|pm)\b")

def _get_soup(url: str):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 5)

    driver.get(url)
    output = driver.page_source
    driver.quit()
    return BeautifulSoup(output, "html.parser")


def _get_agenda(row) -> ScraperReturn:
    def get_col(n):
        return row.css.select("td:nth-of-type(%s)" % n)[0]

    def get_re(soup, r):
        m = r.search(soup.text)
        if not m:
            return None
        return m.group()

    def get_url(n):
        path = get_col(3).find_all('a')[n].get("href")
        redirect = "%s/%s" % (_BUSINESS_PAPER_URL, path)
        return requests.get(redirect).url

    name = get_col(2).text
    date = get_re(get_col(1), _date_re)
    time = get_re(get_col(1).find("span"), _time_re)
    time = time and time.replace('.', ':')

    # The URLs here are redirects so we use
    # requests to get the canonical url.
    web_url = get_url(0)
    pdf_url = get_url(1)

    return ScraperReturn(
        name=name,
        date=date,
        time=time,
        webpage_url=web_url,
        download_url=pdf_url,
    )

def scraper() -> ScraperReturn | None:
    soup = _get_soup(_BUSINESS_PAPER_URL)
    rows = soup.css.select(_BUSINESS_PAPER_ROW_SELECTOR)
    return _get_agenda(rows[0])

parramatta = Council(
    name="parramatta",
    scraper=scraper,
)
