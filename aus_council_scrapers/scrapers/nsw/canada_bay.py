import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_LISTING_URL = "https://www.canadabay.nsw.gov.au/council/about-council/council-meetings"

# Every meeting Canada Bay has published sits on this one page, as accordion
# items: a header carrying the date (and sometimes the meeting type), and a
# panel holding that meeting's documents.
#
# A supplementary agenda is a second document for a meeting that already has
# one, and an attachment book is neither an agenda nor minutes.
_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_SUPPLEMENTARY = re.compile(r"supplementary|attachment", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)


@register_scraper
class CanadaBayScraper(BaseScraper):
    def __init__(self):
        council = "canada_bay"
        state = "NSW"
        base_url = "https://www.canadabay.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = (
            "Canada Bay Civic Centre, 1A Marlborough Street, Drummoyne"
        )
        self.default_time = "6 pm"

    def _meeting_name(self, header_text: str, date: str) -> str:
        qualifier = header_text.replace(date, "").strip(" -–—()")
        if not qualifier:
            return "Council Meeting"
        # The headings are hand-typed, so the qualifier arrives as
        # "Extraordinary" or "extraordinary" depending on the month.
        qualifier = qualifier[0].upper() + qualifier[1:]
        if "meeting" in qualifier.lower():
            return qualifier
        return f"{qualifier} Council Meeting"

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        years_filter = getattr(self, "years_filter", None)
        results: list[ScraperReturn] = []

        for accordion in soup.find_all("div", class_="accordion-list"):
            for item in accordion.find_all("div", class_="list-group-item"):
                header = item.find("a")
                if not header:
                    continue

                header_text = re.sub(r"\s+", " ", header.get_text(" ", strip=True))
                date_match = self.date_regex.search(header_text)
                if not date_match:
                    # A year label ("COUNCIL MEETINGS 2024") rather than a
                    # meeting; it carries no documents of its own.
                    continue

                date = date_match.group()
                if years_filter:
                    year = int(date[-4:])
                    if year not in years_filter:
                        continue

                panel = item.find("div", class_="panel")
                if not panel:
                    continue

                agenda_url = None
                minutes_url = None
                for link in panel.find_all("a", href=True):
                    label = link.get_text(" ", strip=True)
                    href = urljoin(_LISTING_URL, link["href"])
                    if _MINUTES_LABEL.search(label):
                        if minutes_url is None:
                            minutes_url = href
                    elif _AGENDA_LABEL.search(label) and not _SUPPLEMENTARY.search(
                        label
                    ):
                        if agenda_url is None:
                            agenda_url = href

                if not agenda_url and not minutes_url:
                    continue

                results.append(
                    ScraperReturn(
                        name=self._meeting_name(header_text, date),
                        date=date,
                        time=None,
                        webpage_url=_LISTING_URL,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
