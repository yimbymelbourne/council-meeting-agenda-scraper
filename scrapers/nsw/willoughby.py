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
class WilloughbyScraper(BaseScraper):
    def __init__(self):
        council = "willoughby"
        state = "NSW"
        base_url = "https://www.willoughby.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")

        webpage_url = "https://www.willoughby.nsw.gov.au/Council/Council-meetings/General-Council-Meetings"
        response = self.fetch_with_requests(webpage_url)
        if response.status_code != 200:
            self.logger.error("Failed to fetch the main page.")
            return None

        soup = BeautifulSoup(response.content, "html.parser")

        meeting_list_container = soup.find("div", class_="minutes-list-container")
        # Assumes the list is ordered reverse-chronologically and the most recent meeting is first
        first_meeting = meeting_list_container.find(
            "div", class_="accordion-list-item-container"
        )

        # Extract date and type of meeting from the item header
        date_span = first_meeting.find("span", class_="minutes-date")
        date = date_span.text.strip()
        name_span = first_meeting.find("span", class_="meeting-type")
        name = name_span.text.strip()

        # The site loads the body in dynamically,
        # but in the HTML we can retrieve it via a link in the header
        meeting_details_link = first_meeting.find("a", class_="minutes-trigger")
        if not meeting_details_link:
            self.logger.error("Failed to link to meeting details")
            return None
        meeting_details_response = self.fetch_with_requests(
            meeting_details_link["href"]
        )
        if meeting_details_response.status_code != 200:
            self.logger.error("Failed to fetch the meeting details page")
            return None

        meeting_details_soup = BeautifulSoup(
            meeting_details_response.content, "html.parser"
        )

        meeting_body = meeting_details_soup.find("div", class_="meeting-container")

        # Extract the time from the item body
        time_div = meeting_body.find("div", class_="meeting-time")
        time = time_div.find(text=True, recursive=False)

        # May be several documents attached, find the agenda by its header
        download_url = None
        document_divs = meeting_body.find_all("div", class_="meeting-document")
        for div in document_divs:
            div_header = div.find("h2")
            if div_header and div_header.text.strip().lower() == "agenda":
                download_path = div.find("a")["href"]
                download_url = f"{self.base_url}{download_path}"
                break

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


if __name__ == "__main__":
    scraper = WilloughbyScraper()
    scraper.scraper()
