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

        if grandparent_el:
            el_name = grandparent_el.text
            el_name = self.date_regex.sub("", el_name)
            name = el_name

        if name == "" or name is None:
            name = "Council Agenda"

        # Look for minutes link (the scraper is on the minutes page, so look for both)
        minutes_url = None
        agenda_url = download_url  # The first link found is typically the agenda

        # Try to find minutes link by looking in the parent list or nearby section
        if target_a_tag:
            # First try to find the parent ul/ol element
            list_parent = target_a_tag.find_parent(["ul", "ol"])
            if list_parent:
                # Search all links in the same list
                for link in list_parent.find_all("a"):
                    link_text = link.get_text().lower()
                    link_href = link.get("href")
                    # Look for "minute" in text and ensure it's a file link (not a navigation link)
                    if (
                        "minute" in link_text
                        and link_href
                        and not link_href.endswith("/")
                    ):
                        # Handle both relative and absolute URLs
                        if link_href.startswith("http"):
                            minutes_url = link_href
                        else:
                            minutes_url = self.base_url + link_href
                        break

            # If not found in list, try broader search in the parent section
            if not minutes_url and target_a_tag.parent:
                section_parent = target_a_tag.find_parent(["div", "section"])
                if section_parent:
                    for link in section_parent.find_all("a"):
                        link_text = link.get_text().lower()
                        link_href = link.get("href")
                        # Look for "minute" in text and ensure it's a file link
                        if (
                            "minute" in link_text
                            and link_href
                            and not link_href.endswith("/")
                        ):
                            if link_href.startswith("http"):
                                minutes_url = link_href
                            else:
                                minutes_url = self.base_url + link_href
                            break

        print("~~~")
        scraper_return = ScraperReturn(
            name=name,
            date=date,
            time=time,
            webpage_url=webpage_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=download_url,
        )

        print(
            scraper_return.name,
            scraper_return.date,
            scraper_return.time,
            scraper_return.webpage_url,
            scraper_return.agenda_url,
            scraper_return.minutes_url,
            scraper_return.download_url,
        )

        return [scraper_return]
