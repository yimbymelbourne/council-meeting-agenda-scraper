from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class MelbourneScraper(BaseScraper):
    def __init__(self):
        base_url = "https://www.melbourne.vic.gov.au"
        super().__init__("melbourne", "VIC", base_url)
        self.default_location = "Melbourne Town Hall Administration Building, 120 Swanston Street, Melbourne"

    def scraper(self) -> list[ScraperReturn]:

        webpage_url = "https://www.melbourne.vic.gov.au/pages/meetings-finder.aspx?type=41&attach=False"

        # Find next meeting url
        raw_html = self.fetcher.fetch_with_selenium(webpage_url)
        init_soup = BeautifulSoup(raw_html, "html.parser")
        meeting_a = init_soup.select_one("#meetingResults .result a")
        meeting_url = meeting_a["href"]
        meeting_name = meeting_a.get_text()

        # Parse html of next meeting
        meeting_html = self.fetcher.fetch_with_selenium(meeting_url)
        meeting_soup = BeautifulSoup(meeting_html, "html.parser")

        # Date
        date_search = self.date_regex.search(meeting_name)
        date = date_search.group() if date_search else None

        # Extract different variables
        section = meeting_soup.select_one(
            "#ctl00_PlaceHolderMain_EditModePanel2_CouncilMeetingDisplay1 p"
        ).get_text(separator=" ")
        time_search = self.time_regex.search(section)
        time = time_search.group() if time_search else None

        download_soup = meeting_soup.find(
            "a", href=re.compile(r"(.*)agenda(.*).pdf", re.IGNORECASE)
        )
        download_url = self.base_url + download_soup["href"]

        return [ScraperReturn(
            name=meeting_name,
            date=date,
            time=time,
            webpage_url=self.base_url,
            download_url=download_url,
            location=None,
        )]
