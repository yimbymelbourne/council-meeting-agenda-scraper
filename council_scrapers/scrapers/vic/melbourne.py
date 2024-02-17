from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class MelbourneScraper(BaseScraper):
    def __init__(self):
        base_url = "https://www.melbourne.vic.gov.au"
        super().__init__("melbourne", "VIC", base_url)
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"

    def scraper(self) -> ScraperReturn | None:

        webpage_url = "https://www.melbourne.vic.gov.au/pages/meetings-finder.aspx?type=41&attach=False"

        # Get the HTML
        output = self.fetcher.fetch_with_selenium(webpage_url)
        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        name = None
        date = None
        time = None
        download_url = None

        agenda_link = None

        meeting_results = soup.find("div", id="meetingResults")
        if meeting_results:
            result = meeting_results.find("div", class_="result")
            if result:
                link = result.find("a")
                if link:
                    agenda_link = link.get("href")
                    namedate = link.text

                    match = self.date_pattern.search(namedate)

                    if match:
                        extracted_date = match.group()
                        print("Extracted Date:", extracted_date)
                        date = extracted_date

                    name_string = namedate.replace(date, "")
                    if name_string:
                        name = name_string

        new_output = self.fetcher.fetch_with_selenium(agenda_link)
        # Get the HTML

        newsoup = BeautifulSoup(new_output, "html.parser")

        agenda_div = newsoup.find_all("div", class_="download-container")[0]
        if agenda_div:
            pdf_link = agenda_div.find("a", class_="download-link").get("href")
            if pdf_link:
                download_url = self.base_url + pdf_link

        print("~~~")
        scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

        print(
            scraper_return.name,
            scraper_return.date,
            scraper_return.time,
            scraper_return.webpage_url,
            scraper_return.download_url,
        )

        return scraper_return
