from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper, Fetcher
from bs4 import BeautifulSoup
import re


@register_scraper
class GlenEiraScraper(BaseScraper):
    def __init__(self):
        # Initialize with specific council information
        super().__init__("glen_eira", "VIC", "https://www.gleneira.vic.gov.au")
        # Define patterns to extract date and time from text
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.time_pattern = re.compile(r"\b\d{1,2}\.\d{2}(?:am|pm)\b")

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        initial_webpage_url = f"{self.base_url}/about-council/meetings-and-agendas/council-agendas-and-minutes"

        output = self.fetcher.fetch_with_requests(initial_webpage_url)
        initial_soup = BeautifulSoup(output, "html.parser")

        listing_div = initial_soup.find("div", class_="listing__list")
        if listing_div:
            first_meeting_link = listing_div.find("a", class_="listing")
            if first_meeting_link:
                link_to_agenda = first_meeting_link.get("href")
                self.logger.info(f"Found link to agenda: {link_to_agenda}")
                new_url = self.base_url + link_to_agenda

                # Fetch and process the agenda page
                output_new = self.fetcher.fetch_with_requests(new_url)
                soup = BeautifulSoup(output_new, "html.parser")

                # Extract meeting details
                name, date, time, download_url = self.extract_meeting_details(soup)

                self.logger.info(
                    f"Scraped: {name}, Date: {date}, Time: {time}, PDF URL: {download_url}"
                )
                return ScraperReturn(name, date, time, self.base_url, download_url)
        self.logger.error("Failed to find meeting details.")
        return None

    def extract_meeting_details(self, soup):
        name = date = time = download_url = None
        header = soup.find("header")
        if header:
            name = header.find("p", class_="h5").text.strip()
            meeting_datetime = header.find(
                "span", class_="page-title__text"
            ).text.strip()
            date = (
                self.date_pattern.search(meeting_datetime).group(0)
                if self.date_pattern.search(meeting_datetime)
                else "Date not found"
            )

        introduction = soup.find("div", id="introduction")
        if introduction:
            time_match = self.time_pattern.search(introduction.text)
            if time_match:
                extracted_time = time_match.group()
                time = extracted_time
            else:
                print("No time found in the input string.")

        resource_link = soup.find("a", class_="resource__link")
        if resource_link:
            download_url = (
                resource_link.get("href") if resource_link else "PDF link not found"
            )

        return name, date, time, download_url


if __name__ == "__main__":
    scraper = GlenEiraScraper()
    result = scraper.scraper()
    print(result)
