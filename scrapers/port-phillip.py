from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn

import re
date_pattern = r"\b(\d{1,2})\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s(\d{4})\b"
time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"


def scraper() -> ScraperReturn | None:
    webpage_url = 'https://portphillip.infocouncil.biz/'

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)

    driver.get(webpage_url)
    output = driver.page_source

    # Feed HTML to BeautifulSoup
    soup = BeautifulSoup(output, 'html.parser')

    name = None
    date = None
    time = None
    download_url = None

    td_name = soup.find('td', class_='bpsGridCommittee')
    if td_name:
        name = td_name.get_text()
        name = name.rstrip('St Kilda Town Hall')
    else:
        print('td_name not found')

    td_date_time = soup.find('td', class_='bpsGridDate')
    if td_date_time:
        date_time = td_date_time.get_text()
        # splits council-provided "dd mm yytime" into "dd mm yy" + "time"
        split_dt = re.split(r"\s", date_time)
        day = split_dt[0]
        month = split_dt[1]
        year = split_dt[2][:4]
        time = split_dt[2][4:]
        date = day + ' ' + month + ' ' + year
    else:
        print('td_date_time not found')

    td_download_url = soup.find('td', class_='bpsGridAgenda')
    if td_download_url:
        download_url_line = soup.find('a', class_='bpsGridPDFLink')
        if download_url_line:
            link = download_url_line.get('href')
            if link:
                download_url = webpage_url + link
            else:
                print('link not found')
        else:
            print('download_url_line not found')
    else:
        print('td_download_url not found')

    scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

    print(scraper_return.name, scraper_return.date, scraper_return.time, scraper_return.webpage_url,
          scraper_return.download_url)

    return scraper_return


port_phillip = Council(
    name='Port Phillip',
    scraper=scraper,
)

