import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir) 

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
import re


@register_scraper
class PortPhilipScraper(BaseScraper):
    def __init__(self):
        council = "port_philip" 
        state = "VIC"
        base_url = "https://www.portphillip.vic.gov.au/"
        super().__init__( council, state, base_url)
        self.date_pattern = r"\b(\d{1,2})\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s(\d{4})\b"
        self.time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"


    def scraper(self) -> ScraperReturn | None:
        webpage_url = 'https://portphillip.infocouncil.biz/'
        output = self.fetch_with_selenium(webpage_url)
        self.close()

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


if __name__ == "__main__":
    scraper = PortPhilipScraper()
    scraper.scraper()

