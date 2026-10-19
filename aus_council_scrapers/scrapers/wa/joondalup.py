import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.alyka import PageTypeListingScraper, find_date, quote_url
from aus_council_scrapers.base import ScraperReturn, register_scraper

_BASE_URL = "https://www.joondalup.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/city-and-council/council-and-committee-meetings/"
    "council-agenda-and-minutes"
)

# Joondalup's fragment is one `div.document-item` per meeting, as labelled
# cells: Type, Date, Agenda, Minutes, Addendum, Media. Documents link straight
# to PDFs on api.joondalup.wa.gov.au. The Addendum is a second agenda for a
# meeting that already has one, and Media is the YouTube recording, so
# neither is read.
#
# The year filter (`Year`) is the meeting's year, one request per year. The
# listing reaches back to 2000; the cassette starts at EARLIEST_YEAR.
#
# Like Kwinana's, these PDFs answer 406 to this project's fetcher, whose
# Accept header names neither `*/*` nor `application/pdf`, and 200 to a
# browser or Node's fetch. The URLs are emitted as they are.

# The Type cell holds a one-word category.
_MEETING_NAMES = {
    "ordinary": "Ordinary Council Meeting",
    "special": "Special Council Meeting",
    "briefing": "Briefing Session",
    "agm": "Annual General Meeting of Electors",
    "electors": "Special Electors' Meeting",
}


@register_scraper
class JoondalupScraper(PageTypeListingScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("joondalup", "WA", _BASE_URL)

    @staticmethod
    def _cells(item) -> dict:
        cells = {}
        for row in item.find_all(class_="document-item-row"):
            label = row.find(class_="document-item-label")
            value = row.find(class_="document-item-value")
            if label and value:
                cells[label.get_text(" ", strip=True).lower()] = value
        return cells

    @staticmethod
    def _link(cell):
        link = cell.find("a", href=True) if cell else None
        if not link:
            return None
        return quote_url(urllib.parse.urljoin(_BASE_URL, link["href"]))

    def _meetings(self, fragment: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(fragment, "html.parser")
        items = [
            item
            for item in soup.find_all("div", class_="document-item")
            if "document-item-head" not in item.get("class", [])
        ]
        self._warn_if_full(len(items), "a year")

        results = []
        for item in items:
            cells = self._cells(item)
            date_cell = cells.get("date")
            found = (
                find_date(date_cell.get_text(" ", strip=True)) if date_cell else None
            )
            if not found:
                continue
            kind = cells["type"].get_text(" ", strip=True) if "type" in cells else ""
            meeting = self._meeting(
                name=_MEETING_NAMES.get(kind.lower(), f"{kind} Meeting".strip()),
                date=found[0],
                webpage_url=_LISTING_URL,
                agenda_url=self._link(cells.get("agenda")),
                minutes_url=self._link(cells.get("minutes")),
            )
            if meeting:
                results.append(meeting)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        config = self._listing_config(self._listing_page())
        offered = {int(v) for v in self.checkbox_values(config, "Year") if v.isdigit()}
        wanted = self._wanted_years()
        if offered:
            years = sorted(wanted & offered, reverse=True)
        else:
            self.logger.warning(
                f"{self.council_name}: could not read the year filter; "
                f"asking for every wanted year"
            )
            years = sorted(wanted, reverse=True)

        results = []
        for _, fragment in self._each_year(
            years, lambda year: self._search(config, {"Year": [str(year)]})
        ):
            results.extend(
                m for m in self._meetings(fragment) if m.cleaned_date.year in wanted
            )

        self._log_result(results, f"years {years}")
        return results
