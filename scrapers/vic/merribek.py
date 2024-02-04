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
class MerribekScraper(BaseScraper):
    def __init__(self):
        base_url = "https://www.merri-bek.vic.gov.au"
        super().__init__("merri_bek", "Vic", base_url)
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"


    def scraper(self) -> ScraperReturn | None:
        webpage_url = "https://www.merri-bek.vic.gov.au/my-council/council-and-committee-meetings/council-meetings/council-meeting-minutes/"
        output = self.fetch_with_selenium(webpage_url)
        self.close()

        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        name = None
        date = None
        time = None
        download_url = None

        target_a_tag = soup.find("a", href=lambda href: href and "agenda" in href)

        # Print the result
        if target_a_tag:
            print("a tag found")
        else:
            print("No 'a' tag with 'agenda' in the href attribute found on the page.")

        href_value = target_a_tag.get("href")
        if href_value:
            download_url = self.base_url + href_value
            print("download url set")
        else:
            print("link not found.")

        txt_value = target_a_tag.string
        if txt_value:
            match = self.date_pattern.search(txt_value)

            # Extract the matched date
            if match:
                extracted_date = match.group()
                print("Extracted Date:", extracted_date)
                date = extracted_date

            else:
                print("No date found in the input string.")

        grandparent_el = target_a_tag.parent.parent.parent.h3
        el_name = (grandparent_el).text

        el_name = self.date_pattern.sub("", el_name)
        name = el_name

        if name == "":
            name = "Council Agenda"

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


if __name__ == "__main__":
    scraper = MerribekScraper()
    scraper.scraper()