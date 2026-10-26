import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.sharepoint import file_share_download_url

_BASE_URL = "https://www.frasercoast.qld.gov.au"
_LISTING_URL = f"{_BASE_URL}/About-Council/Council-Meetings"

# Fraser Coast Regional Council (QLD).
#
# A documented robots.txt exception. Every agenda and minutes is a SharePoint
# share link on frasercoastregionalcouncil.sharepoint.com, whose robots.txt
# is, in full (checked 26 Oct 2026):
#
#     User-Agent: *
#     Disallow: /
#
# The scraper itself requests only the council's meetings page, which
# www.frasercoast.qld.gov.au/robots.txt allows (it sets no Crawl-delay). But
# council-alerts downloads every document URL a scraper emits, so emitting
# these links fetches the disallowed host. The maintainer decided on 26 Oct
# 2026 to do that anyway, because these papers are the council's official
# public record and its own meetings page links each one for every visitor.
# The load is one download per paper. Nothing else on the SharePoint host
# is requested, and robots.txt is still respected on every other host and
# path.
#
# The share link is a viewer page, so each is emitted in the form that
# returns the PDF itself; see `aus_council_scrapers/sharepoint.py`.
#
# The page holds the current year only, in two tables of one layout: the
# ordinary meeting schedule and special meetings, each under its own h2. The
# columns are Date and Time ("28 January 2026 10am"), Location, Agendas,
# Additional Attachments, Minutes and Livestream Link. Earlier years are in a
# SharePoint folder archive (Archived Meetings), which is not read: a folder
# share has no form a plain client can download from. Informal Council
# Meetings (agenda forums, with a "Record of Matters Discussed" rather than
# minutes) and the Water Advisory Committee (a schedule, no papers) are on
# pages of their own and are not council meetings with minutes.
#
# The Agendas cell also holds "Supplementary Agenda", and the Minutes cell
# "Request for Further Information" and "Minutes Attachments", none of which
# is the paper itself. "Minutes and Attachments" (27 May 2026) is the
# minutes, bound with their attachments.
_TABLE_NAMES = {
    "ordinary meeting schedule": "Ordinary Meeting",
    "special meetings": "Special Meeting",
}
_AGENDA = re.compile(r"^agenda$", re.IGNORECASE)
_MINUTES = re.compile(r"^minutes(?: and attachments)?$", re.IGNORECASE)
# "28 January 2026 10am"; a time is not always given.
_DATE_TIME = re.compile(
    r"^(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*,?\s*(?P<time>\d{1,2}(?:[:.]\d\d)?\s*[ap]m)?",
    re.IGNORECASE,
)


@register_scraper
class FraserCoastScraper(BaseScraper):
    def __init__(self):
        super().__init__("fraser_coast", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _columns(table) -> dict[str, int]:
        header = table.find("tr")
        cells = header.find_all(["th", "td"]) if header else []
        return {c.get_text(" ", strip=True).lower(): i for i, c in enumerate(cells)}

    def _paper(self, cell, pattern: re.Pattern, kind: str, when: str):
        if cell is None:
            return None
        for link in cell.find_all("a", href=True):
            if not pattern.match(" ".join(link.get_text(" ", strip=True).split())):
                continue
            url = file_share_download_url(link["href"])
            if url is None:
                self.logger.warning(
                    f"{self.council_name}: the {kind} of {when} links "
                    f"{link['href']}, which is not a SharePoint file share; left out"
                )
                continue
            return url
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        results = []
        tables_read = 0
        rows_dated = 0
        for table in soup.find_all("table"):
            columns = self._columns(table)
            if not {"date and time", "agendas", "minutes"} <= set(columns):
                continue
            heading = table.find_previous("h2")
            heading_text = heading.get_text(" ", strip=True).lower() if heading else ""
            name = _TABLE_NAMES.get(heading_text)
            if name is None:
                self.logger.warning(
                    f"{self.council_name}: a meetings table under {heading_text!r}, "
                    f"which is not a known body; left out"
                )
                continue
            tables_read += 1
            location_column = columns.get("location")

            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                when = " ".join(cells[columns["date and time"]].get_text(" ", strip=True).split())
                match = _DATE_TIME.match(when)
                if not match:
                    self.logger.warning(f"{self.council_name}: undated row {when!r}; left out")
                    continue
                meeting_date = parse_date(match["date"], dayfirst=True).date()
                rows_dated += 1
                if meeting_date.year not in wanted:
                    continue

                def cell(column):
                    index = columns.get(column)
                    return cells[index] if index is not None and index < len(cells) else None

                agenda_url = self._paper(cell("agendas"), _AGENDA, "agenda", when)
                minutes_url = self._paper(cell("minutes"), _MINUTES, "minutes", when)
                if not agenda_url and not minutes_url:
                    # Listed ahead of time, before its agenda is up.
                    continue
                location = None
                if location_column is not None and location_column < len(cells):
                    location = cells[location_column].get_text(" ", strip=True) or None
                results.append(
                    ScraperReturn(
                        name=name,
                        date=meeting_date.isoformat(),
                        time=match["time"],
                        webpage_url=_LISTING_URL,
                        location=location,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        if not tables_read or not rows_dated:
            # The page loaded but its tables are gone or unreadable: the
            # layout changed, and an empty list would read as no meetings.
            raise RuntimeError(
                f"{self.council_name}: no dated meeting rows at {_LISTING_URL}"
            )
        if not results:
            # The page holds the current year only, so a past year finds
            # nothing, and so may January before the new year's first agenda.
            # Otherwise an empty list means the papers moved.
            today = clock.today()
            if today.year in wanted and today.month >= 3:
                raise RuntimeError(
                    f"{self.council_name}: no papers for {sorted(wanted)} at {_LISTING_URL}"
                )
            self.logger.warning(
                f"{self.council_name}: no papers for {sorted(wanted)} at "
                f"{_LISTING_URL}, which holds the current year only"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
