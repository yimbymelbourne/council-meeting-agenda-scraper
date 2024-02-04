from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from bs4 import BeautifulSoup

from _dataclasses import Council, ScraperReturn


def scraper() -> ScraperReturn | None:
    webpage_url = "https://whitehorse.infocouncil.biz/"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)

    driver.get(webpage_url)
    output = driver.page_source

    # Feed HTML to BeautifulSoup
    soup = BeautifulSoup(output, "html.parser")

    name = None
    date = None
    time = None
    download_url = None

    td_name = soup.find("td", class_="bpsGridCommittee")
    if td_name:
        name = td_name.get_text()
    else:
        print("td_name not found")

    td_date = soup.find("td", class_="bpsGridDate")
    if td_date:
        date = td_date.get_text()
    else:
        print("td_date not found")

    # gets download url
    td_download_url = soup.find("td", class_="bpsGridAgenda")
    if td_download_url:
        download_url_line = soup.find("a", class_="bpsGridPDFLink")
        if download_url_line:
            link = download_url_line.get("href")
            if link:
                download_url = webpage_url + link
            else:
                print("link not found")
        else:
            print("download_url_line not found")
    else:
        print("td_download_url not found")

    scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

    print(
        scraper_return.name,
        scraper_return.date,
        scraper_return.time,
        scraper_return.webpage_url,
        scraper_return.download_url,
    )

    return scraper_return


whitehorse = Council(
    name="Whitehorse",
    scraper=scraper,
)
