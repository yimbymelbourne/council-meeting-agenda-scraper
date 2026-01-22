from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
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
        self.default_location = "Civic Centre Precinct Boxshall Street, Brighton"
        self.default_time = "18:30"

    def scraper(self) -> list[ScraperReturn]:
        initial_webpage_url = "https://www.bayside.vic.gov.au/council/meetings-agendas-and-minutes/council-meeting-agendas"
        minutes_page_url = "https://www.bayside.vic.gov.au/council/meetings-agendas-and-minutes/council-minutes"

        raw_html = self.fetcher.fetch_with_requests(initial_webpage_url)

        # Find latest agenda link
        soup = BeautifulSoup(raw_html, "html.parser")
        agenda_list = soup.find("div", class_="page__body")
        latest_agenda = agenda_list.find("a")

        # Scrape the data
        raw_date = re.search(self.date_regex, latest_agenda.text).group()
        date = "-".join([datetime.strptime(raw_date, "%d %B %Y").strftime("%Y-%m-%d")])
        name = latest_agenda.text.replace(date, "").strip()
        download_url = latest_agenda["href"]

        # Fetch minutes page and find matching minutes
        minutes_url = None
        try:
            minutes_html = self.fetcher.fetch_with_requests(minutes_page_url)
            minutes_soup = BeautifulSoup(minutes_html, "html.parser")
            minutes_list = minutes_soup.find("div", class_="page__body")

            # Find all minutes links and look for one matching the same date
            if minutes_list:
                for link in minutes_list.find_all("a"):
                    link_text = link.get_text()
                    # Check if this minutes link has the same date as the agenda
                    if raw_date in link_text and "minute" in link_text.lower():
                        minutes_url = link["href"]
                        break
        except Exception as e:
            print(f"Error fetching minutes: {e}")

        return [
            ScraperReturn(
                name=name,
                date=date,
                time=None,
                webpage_url=self.base_url,
                agenda_url=download_url,
                minutes_url=minutes_url,
                download_url=download_url,
            )
        ]


if __name__ == "__main__":
    scraper = BaysideVicScraper()
    scraper.scraper()
