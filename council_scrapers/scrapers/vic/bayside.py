from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re
from datetime import datetime


@register_scraper
class BaysideVicScraper(BaseScraper):
    def __init__(self):
        council_name = "bayside_vic"
        state = "VIC"
        base_url = "https://www.bayside.vic.gov.au"
        super().__init__(council_name, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        initial_webpage_url = "https://www.bayside.vic.gov.au/council/meetings-agendas-and-minutes/council-meeting-agendas"

        raw_html = self.fetcher.fetch_with_requests(initial_webpage_url)

        # Find latest agenda link
        soup = BeautifulSoup(raw_html, "html.parser")
        agenda_list = soup.find("div", class_="page__body")
        latest_agenda = agenda_list.find("a")

        # Scrape the data
        raw_date = re.search(self.date_regex, latest_agenda.text).group()
        date = "-".join([datetime.strptime(raw_date, "%d %B %Y").strftime("%Y-%m-%d")])
        time = "18:30"
        name = latest_agenda.text.replace(date, "").strip()
        download_url = latest_agenda["href"]

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
    scraper = BaysideVicScraper()
    scraper.scraper()
