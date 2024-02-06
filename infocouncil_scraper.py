import urllib.parse

from base_scraper import BaseScraper, register_scraper
from _dataclasses import ScraperReturn
from bs4 import BeautifulSoup


class InfoCouncilScraper(BaseScraper):
    def __init__(self, council, state, base_url, infocouncil_url):
        self.infocouncil_url = infocouncil_url
        super().__init__(council, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        output = self.fetch_with_requests(self.infocouncil_url )
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
        date_element = current_meeting.find("td", class_="bpsGridDate")
        if date_element.span is not None:
            time = date_element.span.text
        else:
            time = ""
        scraper_return = ScraperReturn(
            name=current_meeting.find("td", class_="bpsGridCommittee").text,
            date=date_element.contents[0],
            time=time,
            webpage_url=self.infocouncil_url ,
            download_url=urllib.parse.urljoin(self.infocouncil_url, relative_pdf_url),
        )

        self.logger.info(f"{self.council_name} scraper finished successfully")
        return scraper_return
