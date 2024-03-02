from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class MooneeValleyScraper(BaseScraper):
    def __init__(self):
        council = "moonee_valley"
        state = "VIC"
        base_url = "https://mvcc.vic.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:

        webpage_url = "https://mvcc.vic.gov.au/my-council/council-meetings/"

        output = self.fetch_with_selenium(webpage_url)
        self.close()

        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        name = None
        date = None
        time = None
        download_url = None

        table = soup.find_all("table")[0].find("tbody")

        if table:
            # print(table)
            counter = 0
            last_meeting = 0
            set = True
            for child in table.find_all("tr"):
                agenda_text = child.find("td", class_="column-2").text

                if not agenda_text and set:
                    last_meeting = counter
                    set = False
                else:
                    counter = counter + 1
            if set:
                last_meeting = counter

            last_meeting = table.find_all("tr")[last_meeting - 1]

            datetime = last_meeting.find("td", class_="column-1").text

            match = self.date_regex.search(datetime)
            timematch = self.time_regex.search(datetime)

            if match:
                extracted_date = match.group()
                print("Extracted Date:", extracted_date)
                date = extracted_date
            else:
                print("no match found for date")

            if timematch:
                extracted_time = timematch.group()
                print("Extracted Time:", extracted_time)
                time = extracted_time
            else:
                print("no match found for time")

            agenda_link = (
                last_meeting.find("td", class_="column-2").find("a").get("href")
            )
            if agenda_link:
                print(agenda_link)
                download_url = agenda_link

        scraper_return = ScraperReturn(name, date, time, webpage_url, download_url)

        print(
            scraper_return.name,
            scraper_return.date,
            scraper_return.time,
            scraper_return.webpage_url,
            scraper_return.download_url,
        )

        return scraper_return
