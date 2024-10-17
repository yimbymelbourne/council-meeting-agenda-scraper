from aus_council_scrapers.base import BaseScraper, register_scraper
from aus_council_scrapers.data import *
from bs4 import BeautifulSoup
import re

COUNCIL_MEETING_TIME = "6 pm"

@register_scraper
class CanadaBayScraper(BaseScraper):
    def __init__(self):
        council = "canada_bay"
        state = "NSW"
        base_url = "https://www.canadabay.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.default_location = (
            "Canada Bay Civic Centre, 1A Marlborough Street, Drummoyne"
        )

    def scraper(self) -> Results:
        self.logger.info(f"Starting {self.council_name} scraper")

        webpage_url = (
            "https://www.canadabay.nsw.gov.au/council/about-council/council-meetings"
        )

        response = self.fetcher.fetch_with_requests(webpage_url)

        soup = BeautifulSoup(response, "html.parser")

        name = None
        date = None
        download_url = None

        # all links are in the accordian list div
        soup = soup.find("div", class_="accordion-list")

        # first tag with agenda in title
        target_a_tag = soup.find(
            "a", string=lambda string: string and "Agenda" in string
        )

        # Print the result
        if target_a_tag:
            self.logger.debug("a tag found")
        else:
            self.logger.debug(
                "No 'a' tag with 'agenda' in the href attribute found on the page."
            )

        href_value = target_a_tag.get("href")
        if href_value:
            download_url = self.base_url + href_value
            self.logger.debug("download url set")
        else:
            self.logger.debug("link not found.")

        # get the text inside that first name tag - contains both the name of the meeting and the date
        txt_value = target_a_tag.string
        self.logger.debug(txt_value)
        if txt_value:
            # extract the date from txt_value
            match = self.date_pattern.search(txt_value)

            # Extract the matched date
            if match:
                extracted_date = match.group()
                self.logger.info(f"Extracted Date: {extracted_date}")
                date = extracted_date
            else:
                self.logger.debug("No date found in the input string.")

            # extract the name from text value
        name_ = self.date_pattern.sub("", txt_value)
        name = name_.rstrip(" -")  # remove hanging hyphen/whitespace

        if name == "":
            name = "Council Agenda"

        yield ScraperResult.CouncilMeetingNotice(
            name,
            datetime=NoticeDate.FuzzyRaw(date, COUNCIL_MEETING_TIME),
            location=None,
            webpage_url=self.base_url,
            download_url=download_url,
        )
