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
        agendas_page_url = "https://www.bayside.vic.gov.au/council/meetings-agendas-and-minutes/council-meeting-agendas"
        minutes_page_url = "https://www.bayside.vic.gov.au/council/meetings-agendas-and-minutes/council-minutes"

        # Fetch all agendas
        agendas_html = self.fetcher.fetch_with_requests(agendas_page_url)
        agendas_soup = BeautifulSoup(agendas_html, "html.parser")
        agenda_list = agendas_soup.find("div", class_="page__body")

        # Build a dict of meetings from agendas: date -> meeting info
        meetings = {}
        if agenda_list:
            for link in agenda_list.find_all("a"):
                try:
                    link_text = link.get_text(strip=True)
                    date_match = re.search(self.date_regex, link_text)
                    if not date_match:
                        continue

                    raw_date = date_match.group()
                    date = datetime.strptime(raw_date, "%d %B %Y").strftime("%Y-%m-%d")
                    name = link_text.replace(raw_date, "").strip()
                    agenda_url = link["href"]

                    meetings[date] = {
                        "name": name,
                        "date": date,
                        "raw_date": raw_date,
                        "agenda_url": agenda_url,
                        "minutes_url": None,
                    }
                except Exception as e:
                    self.logger.debug(f"Error parsing agenda link: {e}")
                    continue

        # Fetch all minutes and match them to agendas
        try:
            minutes_html = self.fetcher.fetch_with_requests(minutes_page_url)
            minutes_soup = BeautifulSoup(minutes_html, "html.parser")
            minutes_list = minutes_soup.find("div", class_="page__body")

            if minutes_list:
                for link in minutes_list.find_all("a"):
                    try:
                        link_text = link.get_text(strip=True)
                        date_match = re.search(self.date_regex, link_text)
                        if not date_match:
                            continue

                        raw_date = date_match.group()
                        date = datetime.strptime(raw_date, "%d %B %Y").strftime(
                            "%Y-%m-%d"
                        )

                        # If we have an agenda for this date, add the minutes URL
                        if date in meetings:
                            meetings[date]["minutes_url"] = link["href"]
                    except Exception as e:
                        self.logger.debug(f"Error parsing minutes link: {e}")
                        continue
        except Exception as e:
            self.logger.warning(f"Error fetching minutes: {e}")

        # Convert to list of ScraperReturn objects
        results = []
        for meeting in meetings.values():
            results.append(
                ScraperReturn(
                    name=meeting["name"],
                    date=meeting["date"],
                    time=None,
                    webpage_url=self.base_url,
                    agenda_url=meeting["agenda_url"],
                    minutes_url=meeting["minutes_url"],
                    download_url=meeting["agenda_url"],
                )
            )

        # Sort by date descending (newest first)
        results.sort(key=lambda x: x.date, reverse=True)

        return results


if __name__ == "__main__":
    scraper = BaysideVicScraper()
    scraper.scraper()
