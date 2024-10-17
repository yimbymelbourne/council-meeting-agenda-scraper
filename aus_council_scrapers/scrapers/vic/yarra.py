import datetime
from aus_council_scrapers.data import ScraperResult
from aus_council_scrapers.base import BaseScraper, register_scraper
from bs4 import BeautifulSoup
from typing import Generator
import re
from dateutil.parser import parse as parse_date


@register_scraper
class YarraScraper(BaseScraper):
    def __init__(self):
        council = "yarra"
        state = "VIC"
        base_url = "https://www.yarracity.vic.gov.au"
        super().__init__(council, state, base_url)

    def is_future_meeting(self, element):
        text = element.get_text(separator=" ")
        date = re.search(self.date_regex, text)
        grouped_date = date.group() if date else None
        if not grouped_date:
            return False
        parsed_date = parse_date(grouped_date).date()
        if parsed_date >= datetime.datetime.now().date():
            return True

    def scraper(self) -> Generator[ScraperResult, None]:

        initial_webpage_url = "https://www.yarracity.vic.gov.au/about-us/council-and-committee-meetings/upcoming-council-and-committee-meetings"

        output = self.fetcher.fetch_with_requests(initial_webpage_url)
        output = output

        name = None
        date = None
        time = None
        download_url = None
        agenda_link = None

        # finds agenda link
        initial_soup = BeautifulSoup(output, "html.parser")
        agenda_list = initial_soup.find("div", class_="show-for-medium-up")
        agenda_link = [
            element["href"]
            for element in agenda_list.find_all("a")
            if self.is_future_meeting(element)
        ][0]

        agenda_output = self.fetcher.fetch_with_requests(agenda_link)

        # takes name, date, download url from agenda link
        soup = BeautifulSoup(agenda_output, "html.parser")

        name = soup.find("h1", class_="heading").text

        date_time_p = soup.find("strong", string="Date and time:").find_parent("p")
        date_time = date_time_p.get_text(strip=True, separator=" ")
        time_match = re.search(self.time_regex, date_time)
        date_match = re.search(self.date_regex, date_time)
        time = time_match.group().replace(".", ":") if time_match else None
        date = date_match.group()

        location = (
            soup.find("strong", string="Address:")
            .find_parent("p")
            .text.replace("Address:", "")
            .strip()
        )

        download_url = soup.find("a", class_="download-link")["href"]
        download_url = self.base_url + download_url

        yield ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=self.base_url,
            download_url=download_url,
            location=location,
        )


if __name__ == "__main__":
    scraper = YarraScraper()
    scraper.scraper()
