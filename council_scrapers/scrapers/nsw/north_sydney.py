from council_scrapers.base import BaseScraper, register_scraper, ScraperReturn
from bs4 import BeautifulSoup
import re


@register_scraper
class NorthSydneyScraper(BaseScraper):

    def __init__(self):
        council = "north_sydney"
        state = "NSW"
        base_url = "https://www.northsydney.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        webpage_url = "https://www.northsydney.nsw.gov.au/council-meetings"

        name = None
        date = None
        time = None
        download_url = None

        output = self.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output.content, "html.parser")
        nextUrl = soup.find("a", class_="listing__link")["href"]

        meetingPage = self.fetch_with_requests(f"{self.base_url}{nextUrl}")
        soup = BeautifulSoup(meetingPage.content, "html.parser")

        links = soup.find_all("a", class_="listing__link")
        filtered_links = [link for link in links if "agenda" in link.text.lower()]

        for link in filtered_links:
            href = link.get("href")
            text = link.text.strip()
            download_url = f"{self.base_url}{href}"

        section = soup.find("section", class_="site-content")
        if section:
            container = section.find("div", class_="container")
            if container:
                page_heading = container.find("h1", class_="page-heading")
                if page_heading:
                    heading_text = page_heading.text.strip()
                    regex = r"(\d{2}/\d{2}/\d{4})\s+(.*)"
                    match = re.search(regex, heading_text)
                    if match:
                        date = match.group(1)  # Extracted date
                        name = match.group(2)

        scraper_return = ScraperReturn(name, date, "", self.base_url, download_url)
        self.logger.info(f"{self.council_name} scraper finished successfully")

        self.logger.info(
            f"""
            {scraper_return.name} 
            {scraper_return.date} 
            {scraper_return.time} 
            {scraper_return.webpage_url} 
            {scraper_return.download_url}"""
        )
        return scraper_return
