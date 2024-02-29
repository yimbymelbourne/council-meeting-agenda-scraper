from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class YarraScraper(BaseScraper):
    def __init__(self):
        council = "yarra"
        state = "VIC"
        base_url = "https://www.yarracity.vic.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        initial_webpage_url = "https://www.yarracity.vic.gov.au/about-us/council-and-committee-meetings/upcoming-council-and-committee-meetings"

        output = self.fetcher.fetch_with_requests(initial_webpage_url)
        output = output

        name = None
        date = None
        time = None
        download_url = None
        agenda_link = None

        # finds agenda link
        initial_soup = BeautifulSoup(output, "html.parser")
        agenda_list = initial_soup.find("div", class_="show-for-medium-up")
        agenda_link = agenda_list.find("a")["href"]
        agenda_output = self.fetcher.fetch_with_requests(agenda_link)

        # takes name, date, download url from agenda link
        soup = BeautifulSoup(agenda_output, "html.parser")

        name = soup.find("h1", class_="heading").text

        date_time_p = soup.find("strong", string="Date and time:").find_parent("p")
        date_time = date_time_p.get_text(strip=True)
        time_match = re.search(self.time_regex, date_time)
        date_match = re.search(self.date_regex, date_time)
        time = time_match.group().replace(".", ":") if time_match else None
        date = date_match.group()

        download_url = soup.find("a", class_="download-link")["href"]
        download_url = self.base_url + download_url

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
    scraper = YarraScraper()
    scraper.scraper()
