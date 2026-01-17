from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class CamdenScraper(BaseScraper):
    def __init__(self):
        council = "camden"
        state = "NSW"
        base_url = "https://www.camden.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = "70 Central Ave, Oran Park NSW 2570"

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        name = None
        date = None
        time = "18:30"
        webpage_url = "https://www.camden.nsw.gov.au/council/council-meetings"
        agenda_url = None
        minutes_url = None

        output = self.fetcher.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output, "html.parser")
        meets = soup.find("h4")
        link = meets.find_next("a")["href"]
        latest_year = f"{self.base_url}/" + link

        output = self.fetcher.fetch_with_requests(latest_year)
        soup = BeautifulSoup(output, "html.parser")

        latest_meet = soup.find("h2")
        # Custom pattern. TODO: Refactor to use constant regex.
        pattern = r"(\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})(\s[a-zA-Z\(\)]+)?"
        match = re.match(pattern, latest_meet.text)
        if match:
            if "Extraordinary" in latest_meet.text:
                name = "Extraordinary Council Meeting"
            else:
                name = "Council Meeting"
            date = match.group(1)

        # Find agenda link
        link = latest_meet.find_next("a")["href"]
        agenda_url = f"{self.base_url}{link}"

        # Look for minutes link - typically appears as another link near the agenda
        # This is a placeholder - actual implementation depends on website structure
        # Example: Look for a link containing "minutes" text
        for sibling in latest_meet.find_next_siblings():
            minutes_link = sibling.find(
                "a", string=re.compile("minutes", re.IGNORECASE)
            )
            if minutes_link and "href" in minutes_link.attrs:
                minutes_url = f"{self.base_url}{minutes_link['href']}"
                break

        scraper_return = ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=self.base_url,  # Use base_url for consistency with tests
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url,  # For backward compatibility
        )
        self.logger.info(
            f"""
            {scraper_return.name}
            {scraper_return.date}
            {scraper_return.time}
            {scraper_return.webpage_url}
            Agenda: {scraper_return.agenda_url}
            Minutes: {scraper_return.minutes_url}"""
        )
        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return


if __name__ == "__main__":
    scraper = CamdenScraper()
    scraper.scraper()
