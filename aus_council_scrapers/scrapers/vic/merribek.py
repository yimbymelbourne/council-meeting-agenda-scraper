from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
    Fetcher,
)
from bs4 import BeautifulSoup
import re


@register_scraper
class MerribekScraper(BaseScraper):
    def __init__(self):
        base_url = "https://www.merri-bek.vic.gov.au"
        super().__init__("merri_bek", "VIC", base_url)

    def scraper(self) -> list[ScraperReturn]:
        print(f"Starting {self.council_name} scraper")
        webpage_url = "https://www.merri-bek.vic.gov.au/my-council/council-and-committee-meetings/council-meetings/council-meeting-minutes/"
        output = self.fetcher.fetch_with_requests(webpage_url)

        # Feed the HTML to BeautifulSoup
        soup = BeautifulSoup(output, "html.parser")

        # Dictionary to store meetings by date
        meetings = {}

        # Find all agenda links on the page
        agenda_links = soup.find_all(
            "a",
            href=lambda href: href
            and "agenda" in href.lower()
            and href.endswith(".pdf"),
        )

        print(f"Found {len(agenda_links)} agenda links")

        for link in agenda_links:
            link_text = link.get_text().strip()
            link_href = link.get("href")

            # Skip if no href
            if not link_href:
                continue

            # Extract date from link text
            match = self.date_regex.search(link_text)
            if not match:
                continue

            date = match.group()

            # Build full URL
            if link_href.startswith("http"):
                agenda_url = link_href
            else:
                agenda_url = self.base_url + link_href

            # Extract name - try to get from h3 parent or use link text
            name = None
            try:
                grandparent_el = link.find_parent(["ul", "ol"])
                if grandparent_el:
                    h3_parent = grandparent_el.find_previous("h3")
                    if h3_parent:
                        name = h3_parent.get_text().strip()
                        name = self.date_regex.sub("", name).strip()
            except:
                pass

            if not name or name == "":
                # Use the link text without the date
                name = self.date_regex.sub("", link_text).strip()

            if not name or name == "":
                name = "Council Meeting"

            # Store the meeting
            meetings[date] = {
                "name": name,
                "date": date,
                "agenda_url": agenda_url,
                "minutes_url": None,
            }

        # Now find all minutes links and match them to agendas by date
        minutes_links = soup.find_all(
            "a",
            href=lambda href: href
            and "minute" in href.lower()
            and href.endswith(".pdf"),
        )

        print(f"Found {len(minutes_links)} minutes links")

        for link in minutes_links:
            link_text = link.get_text().strip()
            link_href = link.get("href")

            if not link_href:
                continue

            # Extract date from link text
            match = self.date_regex.search(link_text)
            if not match:
                continue

            date = match.group()

            # Build full URL
            if link_href.startswith("http"):
                minutes_url = link_href
            else:
                minutes_url = self.base_url + link_href

            # If we have an agenda for this date, add the minutes URL
            if date in meetings:
                meetings[date]["minutes_url"] = minutes_url

        # Convert to list of ScraperReturn objects
        results = []
        for date, meeting_data in sorted(
            meetings.items(), key=lambda x: x[0], reverse=True
        ):
            scraper_return = ScraperReturn(
                name=meeting_data["name"],
                date=meeting_data["date"],
                time=None,
                webpage_url=webpage_url,
                agenda_url=meeting_data["agenda_url"],
                minutes_url=meeting_data["minutes_url"],
                download_url=meeting_data["agenda_url"],
            )
            results.append(scraper_return)

        print(f"Returning {len(results)} meetings")
        return results
