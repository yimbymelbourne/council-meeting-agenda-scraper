from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper, Fetcher
from bs4 import BeautifulSoup
import re


@register_scraper
class MerribekScraper(BaseScraper):
    def __init__(self):
        base_url = "https://www.merri-bek.vic.gov.au"
        super().__init__("merri_bek", "VIC", base_url)

    def scraper(self) -> ScraperReturn | None:
        print(f"Starting {self.council_name} scraper")
        webpage_url = "https://www.merri-bek.vic.gov.au/my-council/council-and-committee-meetings/council-meetings/council-meeting-minutes/"
        output = self.fetcher.fetch_with_requests(webpage_url)

        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        name = None
        date = None
        time = None
        download_url = None

        target_a_tag = soup.find("a", href=lambda href: href and "agenda" in href)

        # Print the result
        if target_a_tag:
            print("a tag found")
        else:
            print("No 'a' tag with 'agenda' in the href attribute found on the page.")

        href_value = target_a_tag.get("href")
        if href_value:
            download_url = self.base_url + href_value
            print("download url set")
        else:
            print("link not found.")

        txt_value = target_a_tag.string
        if txt_value:
            match = self.date_regex.search(txt_value)

            # Extract the matched date
            if match:
                extracted_date = match.group()
                print("Extracted Date:", extracted_date)
                date = extracted_date

            else:
                print("No date found in the input string.")

        grandparent_el = target_a_tag.parent.parent.parent.h3
        el_name = (grandparent_el).text

        el_name = self.date_regex.sub("", el_name)
        name = el_name

        if name == "":
            name = "Council Agenda"

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
