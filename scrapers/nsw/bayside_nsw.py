import sys
from pathlib import Path

parent_dir = str(Path(__file__).resolve().parent.parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from base_scraper import BaseScraper, register_scraper
from logging.config import dictConfig
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup


@register_scraper
class BaysideNSWScraper(BaseScraper):
    def __init__(self):
        council = "bayside_nsw"
        state = "nsw"
        base_url = "https://baysdie.nsw.gov.au"
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        url = "https://infoweb.bayside.nsw.gov.au/?committee=1"
        output = self.fetch_with_requests(url)
        soup = BeautifulSoup(output.content, "html.parser")
        meeting_table = soup.find("table", id="grdMenu", recursive=True)
        if meeting_table is None:
            self.logger.info(f"{self.council_name} scraper found no meetings")
            scraper_return = ScraperReturn(
                name=None, date=None, time=None, webpage_url=None, download_url=None
            )
            return scraper_return
        current_meeting = meeting_table.find("tbody").find_all("tr")[0]

        relative_pdf_url = current_meeting.find(
            "a", class_="bpsGridPDFLink", recursive=True
        ).attrs["href"]
        scraper_return = ScraperReturn(
            name=current_meeting.find("td", class_="bpsGridCommittee").text,
            date=current_meeting.find("td", class_="bpsGridDate").text,
            time="",
            webpage_url=url,
            download_url=f"{url}/{relative_pdf_url}",
        )

        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return


if __name__ == "__main__":
    scraper = BaysideNSWScraper()
    scraper.scraper()
