from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re

AGENGA_REGEX = re.compile(r"(.*)agenda(.*)", re.IGNORECASE)


@register_scraper
class BoroondaraScraper(BaseScraper):
    def __init__(self):
        council = "boroondara"
        state = "VIC"
        base_url = "https://www.boroondara.vic.gov.au"
        super().__init__(council, state, base_url)
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.time_pattern = re.compile(r"\b\d{1,2}:\d{2} [apmAPM]+\b")

    def scraper(self) -> ScraperReturn | None:
        initial_webpage_url = "https://www.boroondara.vic.gov.au/your-council/councillors-and-meetings/council-and-committee-meetings"

        # Find next meeting url
        raw_html = self.fetcher.fetch_with_requests(initial_webpage_url)
        init_soup = BeautifulSoup(raw_html, "html.parser")
        meeting_a = init_soup.select_one("article a.event-teaser")["href"]
        meeting_url = self.base_url + meeting_a

        # Parse html of next meeting
        meeting_html = self.fetcher.fetch_with_requests(meeting_url)
        meeting_soup = BeautifulSoup(meeting_html, "html.parser")

        # Extract different variables
        datetime_soup = meeting_soup.select_one(".group-datetime")
        date = datetime_soup.select_one("span").get_text(strip=True)
        time = datetime_soup.select_one("span.start-time").get_text(strip=True)

        location_soup = meeting_soup.select_one(".event-location-reference")
        location = location_soup.select_one(".address").get_text().replace("\n", " ")

        download_soup = meeting_soup.find("a", attrs={"data-filetype": "PDF"})
        download_url = self.base_url + download_soup["href"]

        return ScraperReturn(
            name=None,
            date=date,
            time=time,
            webpage_url=self.base_url,
            download_url=download_url,
            location=location,
        )
