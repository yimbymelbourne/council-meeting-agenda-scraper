from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper, Fetcher
from bs4 import BeautifulSoup
import re


@register_scraper
class RydeScraper(BaseScraper):
    def __init__(self):
        council = "ryde"
        state = "NSW"
        base_url = "https://www.ryde.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        name = None
        date = None
        time = None
        webpage_url = "https://www.ryde.nsw.gov.au/Council/Council-Meetings/Council-Meeting-agendas-and-minutes"
        download_url = None

        output = self.fetcher.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output, "html.parser")
        next_url = soup.find("article").find("a")["href"]

        meeting_page = self.fetcher.fetch_with_requests(next_url)
        soup = BeautifulSoup(meeting_page, "html.parser")

        # name and date
        name_date = soup.find("h1", class_="oc-page-title").text
        pattern = r"([a-zA-Z\s]+)-\s+(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})"
        match = re.match(pattern, name_date)
        if match:
            name = match.group(1)
            date = match.group(2)

        # link
        link = soup.find("a", {"title": "Agenda"})["href"]
        download_url = f"{self.base_url}{link}"

        scraper_return = ScraperReturn(name, date, time, self.base_url, download_url)

        self.logger.info(
            f"""
            {scraper_return.name}
            {scraper_return.date}
            {scraper_return.time}
            {scraper_return.webpage_url}
            {scraper_return.download_url}"""
        )
        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return
