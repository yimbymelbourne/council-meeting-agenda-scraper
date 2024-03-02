from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper, Fetcher
from bs4 import BeautifulSoup


@register_scraper
class CanterburyBankstownScraper(BaseScraper):
    def __init__(self):
        council = "canterbury_bankstown"
        state = "NSW"
        base_url = "https://www.cbcity.nsw.gov.au/"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn:
        self.logger.info(f"Starting {self.council_name} scraper")

        name = None
        date = None
        time = "18:30"
        webpage_url = "https://www.cbcity.nsw.gov.au/council/Councilmeetings-reports-committees/council-meeting-agendas-minutes"
        download_url = None

        output = self.fetcher.fetch_with_requests(webpage_url)
        soup = BeautifulSoup(output, "html.parser")

        latest_meet = soup.find("tr", class_="ms-rteTableOddRow-4")
        date = latest_meet.find_next("td").contents[0]
        name = date.find_next("td").contents[0]
        link = name.find_next("td").find("a")["href"]
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
