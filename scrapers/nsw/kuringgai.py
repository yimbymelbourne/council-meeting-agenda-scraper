
# Copied base code from the Bayside scraper by Canoon

import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup
import re


@register_scraper
class KuringgaiScraper(BaseScraper):
    BUSINESS_PAPER_ROW_SELECTOR = "#grdMenu tbody > tr"
    date_re = re.compile(
        r"\b(\d{1,2})\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s(\d{4})"
    )
    time_re = re.compile(r"\b(\d{1,2}:\d{2})(am|pm)\b")

    def __init__(self):
        council = "kuringgai"
        state = "nsw"
        base_url = "http://www.krg.nsw.gov.au/Council/Council-meetings/Minutes-and-agendas"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        output = self.fetch_with_requests(self.base_url)
        self.close()
        soup = BeautifulSoup(output.content, "html.parser")
        first_row = soup.select_one(self.BUSINESS_PAPER_ROW_SELECTOR)
        if not first_row:
            self.logger.error("No Business paper rows found")
            return ScraperReturn("", "", "", self.base_url, "")
        else:
            name = first_row.select_one(".bpsGridCommittee").text.strip()

            date_match = self.date_re.search(first_row.text)
            date = date_match.group(0) if date_match else ""

            time_match = self.time_re.search(first_row.text)
            time = time_match.group(0) if time_match else ""

            pdf_link_element = first_row.select_one("a.bpsGridPDFLink")
            pdf_url = (
                pdf_link_element["href"] if pdf_link_element else "PDF link not found"
            )
            download_url = (
                f"{self.base_url}/{pdf_url}"
                if pdf_url != "PDF link not found"
                else pdf_url
            )
            self.logger.info(
                f"Scraped: {name}, Date: {date}, Time: {time}, PDF URL: {download_url}"
            )
            scraper_return = ScraperReturn(
                name, date, time, self.base_url, download_url
            )
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


if __name__ == "__main__":
    scraper = KuringgaiScraper()
    scraper.scraper()
