from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
from datetime import datetime


@register_scraper
class WollongongScraper(BaseScraper):
    def __init__(self):
        print("Wollongong")
        council_name = "wollongong"
        state = "NSW"
        base_url = "https://www.wollongong.nsw.gov.au/"
        super().__init__(council_name, state, base_url)

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")

        business_papers_url = "https://www.wollongong.nsw.gov.au/council/council-meetings/councilbusinesspapers"

        name = None
        date = None
        time = None
        download_url = None

        # Retrieve business papers page
        output = self.fetcher.fetch_with_requests(business_papers_url)

        # Convert to soup
        initial_soup = BeautifulSoup(output, "html.parser")

        # Find the table with class 'buspaper'
        buspaper_table = initial_soup.find("table", class_="buspaper")

        # Table should exist, so throw error if it doesn't
        if not buspaper_table:
            self.logger.info(f"{self.council_name} Business paper table not found")
            raise ValueError(
                "The buspaper_table with class 'buspaper' was not found in the HTML content."
            )

        # Extract rows from the buspaper_table
        rows = buspaper_table.find_all("tr")[1:]  # Skip the header row if it exists

        # Extract agendas from business papers table
        agendas = []
        for row in rows:
            cells = row.find_all("td")

            # Skip rows where the 3rd column is not 'Agenda'
            if cells[2].get_text(strip=True) != "Agenda":
                continue

            # Extract the meeting date, agenda name, and URL
            meeting_date = datetime.strptime(cells[1].get_text(strip=True), "%d %b %Y")
            link = cells[3].find("a")
            agenda_name = link.get_text(strip=True)
            agenda_url = link.get("href")

            # Append a dictionary with the extracted data to the agendas list
            agendas.append(
                {
                    "meeting_date": meeting_date,
                    "agenda_name": agenda_name,
                    "agenda_url": agenda_url,
                }
            )

        # Get agenda with most recent meeting date
        # TODO: this gets most recent agenda even if it is in the past. Should it only
        # get agenda in the future?
        most_recent_agenda = max(agendas, key=lambda x: x["meeting_date"])

        name = most_recent_agenda["agenda_name"]
        date = most_recent_agenda["meeting_date"].strftime("%Y-%m-%d")
        download_url = most_recent_agenda["agenda_url"]

        scraper_return = ScraperReturn(
            name,
            date,
            time,
            self.base_url,
            download_url,
        )

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
