from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class BoroondaraScraper(BaseScraper):
    def __init__(self):
        council = "boroondara"
        state = "VIC"
        base_url = "https://www.boroondara.vic.gov.au"
        super().__init__(council, state, base_url)
        self.date_pattern = re.compile(
            r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        )
        self.time_pattern = re.compile(r"\b\d{1,2}:\d{2} [apmAPM]+\b")

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        initial_webpage_url = "https://www.boroondara.vic.gov.au/about-council/councillors-and-meetings/council-and-committee-meetings/past-meeting-minutes-agendas-and-video-recordings"

        output = self.fetcher.fetch_with_requests(initial_webpage_url)
        # boroondara doesn't have the agenda pdfs on the same page as the list of meetings - need to first find the link to the newest agenda and then read source from that page

        name = None
        date = None
        time = None
        download_url = None
        link_to_agenda = None

        # Feed the HTML to BeautifulSoup
        initial_soup = BeautifulSoup(output, "html.parser")

        node_content = initial_soup.find("div", class_="node__content")
        if node_content:
            first_link = node_content.find("a")
            self.logger.debug(first_link)

            link_to_agenda = first_link.get("href")
            self.logger.info(link_to_agenda)
            date_and_time = first_link.find("span", class_="occurrence-date").text
            self.logger.info(f"Datetime: {date_and_time}")

            if date_and_time:
                date_match = self.date_pattern.search(date_and_time)
                # Extract the matched date
                if date_match:
                    extracted_date = date_match.group()
                    self.logger.info(f"Extracted Date: {extracted_date}")
                    date = extracted_date
                else:
                    self.logger.warning("No date found in the input string.")

                time_match = self.time_pattern.search(date_and_time)

                # Extract the matched time
                if time_match:
                    extracted_time = time_match.group()
                    self.logger.info(f"Extracted Date: {extracted_time}")
                    time = extracted_time
                else:
                    self.logger.warning("No time found in the input string.")

        else:
            self.logger.warning("failed to find node content")

        # finding and reading current agenda page

        new_url = self.base_url + link_to_agenda
        self.logger.info(new_url)

        output_new = self.fetcher.fetch_with_requests(new_url)

        # Get the HTML
        soup = BeautifulSoup(output_new, "html.parser")

        # first need to find the agenda h3 because the divs of interest are below it
        div = soup.find("div", class_="main")
        if div:
            agenda_h3 = div.find("h3")
            if agenda_h3:
                # print(agenda_h3)
                div_container = agenda_h3.parent.find("div", class_="download-links")
                if div_container:
                    # for child in div_container.find_all('span', class_ = 'file-date'):
                    # print(child.text)
                    # TODO: fix the logic because you can't assume the newest agenda is always on the end!

                    n_children = len(div_container.find_all("a", class_="file-link"))
                    latest_agenda = div_container.find_all("a", class_="file-link")[
                        n_children - 1
                    ].get("href")
                    if latest_agenda:
                        download_url = self.base_url + latest_agenda
                    name_ = div_container.find_all("a", class_="file-link")[
                        n_children - 1
                    ].get("data-filename")
                    if name_:
                        name = name_
                else:
                    self.logger.error("error cant make div container")
            else:
                self.logger.warning("no agenda h3")

        else:
            self.logger.warning("no div")

        # print("~~~")
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
