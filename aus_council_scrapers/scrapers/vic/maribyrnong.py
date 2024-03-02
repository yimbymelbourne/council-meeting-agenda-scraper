from council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from bs4 import BeautifulSoup
import re


@register_scraper
class MaribyrnongScraper(BaseScraper):
    def __init__(self):
        council_name = "maribyrnong"
        state = "VIC"
        base_url = "https://www.maribyrnong.vic.gov.au/"
        super().__init__(council_name, state, base_url)
        self.date_pattern = r"\b(\d{1,2})\s(January|February|March|April|May|June|July|August|September|October|November|December)\s(\d{4})\b"
        self.time_pattern = r"\b(\d{1,2}:\d{2})\s(AM|PM)\b"

    def scraper(self) -> ScraperReturn | None:
        self.logger.info(f"Starting {self.council_name} scraper")
        webpage_url = "https://www.maribyrnong.vic.gov.au/About-us/Council-and-committee-meetings/Agendas-and-minutes"
        response = self.fetch_with_requests(webpage_url)
        if response.status_code != 200:
            self.logger.error("Failed to fetch the main page.")
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        latest_meeting_link = soup.find(
            "a", class_="accordion-trigger minutes-trigger ajax-trigger"
        )["href"]
        self.logger.debug(f"Latest meeting link: {latest_meeting_link}")

        meeting_response = self.fetch_with_requests(latest_meeting_link)
        if meeting_response.status_code != 200:
            self.logger.error("Failed to fetch the latest meeting page.")
            return None

        soup = BeautifulSoup(meeting_response.content, "html.parser")
        meeting_container = soup.find("div", class_="meeting-container")
        if not meeting_container:
            self.logger.error("Meeting container not found.")
            return None

        name_date_details = soup.find(
            "ul", class_="content-details-list minutes-details-list"
        )
        if name_date_details:
            # Attempt to find all 'li' elements directly and then iterate to find specific details
            list_items = name_date_details.find_all("li")
            meeting_date, meeting_type = None, None
            for li in list_items:
                field_label = li.find("span", class_="field-label")
                field_value = li.find("span", class_="field-value")
                if field_label and field_value:  # Ensure both elements are found
                    label_text = field_label.text.strip()
                    value_text = field_value.text.strip()
                    if "Meeting Date" in label_text:
                        # If the 'minutes-date' span is present, use it; otherwise, use the general field value.
                        date_span = field_value.find("span", class_="minutes-date")
                        date = date_span.text.strip() if date_span else value_text
                    elif "Meeting Type" in label_text:
                        name = value_text

        # Extract meeting time
        time_div = meeting_container.find("div", class_="meeting-time")
        if time_div:
            time = time_div.text.strip()
            time = re.search(r"\d{1,2}:\d{2}\s(?:AM|PM)", time).group(0)
        else:
            self.logger.error("Meeting time not found.")
            time = None

        # Extract agenda PDF link
        agenda_div = meeting_container.find("div", class_="meeting-document")
        if agenda_div:
            meeting_name = agenda_div.find(
                "h2"
            )  # This may need adjustment if the structure is different
            if meeting_name:
                docName = meeting_name.text.strip()
                if docName == "Agenda":
                    agenda_link = agenda_div.find("a", class_="document ext-pdf")
                    if agenda_link and "href" in agenda_link.attrs:
                        download_url = agenda_link["href"]
                        if not download_url.startswith("http"):
                            download_url = (
                                "https://www.maribyrnong.vic.gov.au" + download_url
                            )
                else:
                    self.logger.error("Agenda link not found.")
                    download_url = None
            else:
                self.logger.error("Meeting name not found.")
                name = "Unknown Meeting"

        else:
            self.logger.error("Agenda document div not found.")
            download_url = None

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
