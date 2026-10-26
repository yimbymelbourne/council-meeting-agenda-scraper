import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from requests.utils import requote_uri

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

# Two dateutil defaults that differ in year, month and day (see _parse_table).
_DEFAULT_A = datetime(2000, 1, 1)
_DEFAULT_B = datetime(2001, 2, 2)

_LISTING_URL = "https://www.goomalling.wa.gov.au/council-meetings/"

# Goomalling runs on Market Creations' CouncilConnect CMS, but not through its
# meetings module: the module's 2025 meeting pages carry no documents, and
# /council-meetings/past/<year> is a 404. The papers are in hand-built tables
# on this one content page instead, a table per year under an "<year>
# Agendas & Minutes" heading, with columns Meeting | Date | Agenda | Minutes |
# Recording. One request covers 2020 to now.
#
# The tables are typed by hand, so their shape drifts: the 2024 table heads
# its minutes column "Meeting", the 2020 table has no agenda column, and a
# cell can hold an agenda plus attachments, late items or the adopted budget.
# So papers are told apart by their link text ("Agenda - October 2026",
# "Minutes 0423"), which names the paper on every row, not by column.
#
# Signed minutes are scans named for the meeting that confirmed them
# ("Minutes_2025-10-15_..._Confirmed_and_Signed.pdf" is the 17 September 2025
# minutes, signed on 15 October), and some are bare scanner names
# (20250925121145739.pdf). The row's date is the meeting's; filenames are
# never read for it.
#
# The table under "2026 Meetings" at the top is the year's schedule, with
# no papers, and the next scheduled meeting is a row in the 2026 papers table
# anyway (with empty cells until its agenda is up).

_PAPERS_HEADING = re.compile(r"^(\d{4}) (?:Agendas & )?Minutes$")
_EXTRA = re.compile(r"\blate\b|attachment|recording", re.IGNORECASE)
# Not \b: "Minutes_EM_170521" and "Agenda0723" run the word into the rest.
_AGENDA = re.compile(r"(?<![a-z])agenda", re.IGNORECASE)
_MINUTES = re.compile(r"(?<![a-z])min(?:utes|tues)(?![a-z])", re.IGNORECASE)
# "2024/2025Annual Electors Meeting", "2021/22 AGM of Electors": the
# financial year whose annual report the electors meet on.
_FINANCIAL_YEAR = re.compile(r"^\d{4}/\d{2,4}\s*")

_NAMES = {
    "ARIC Meeting": "Audit, Risk and Improvement Committee Meeting",
    "Audit and Risk Committee": "Audit and Risk Committee Meeting",
    "AGM of Electors": "Annual Electors Meeting",
    "Electors Meeting": "Annual Electors Meeting",
}


@register_scraper
class GoomallingScraper(BaseScraper):
    def __init__(self):
        super().__init__("goomalling", "WA", "https://www.goomalling.wa.gov.au")

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        years_filter = getattr(self, "years_filter", None)
        results: list[ScraperReturn] = []

        for heading in soup.find_all("h3"):
            match = _PAPERS_HEADING.match(heading.get_text(" ", strip=True))
            if not match:
                continue
            year = int(match.group(1))
            if years_filter and year not in years_filter:
                continue
            # The 2026 heading is followed by an empty header-only table and
            # then the real one, so read every table up to the next heading.
            for table in self._tables_after(heading):
                results.extend(self._parse_table(table, year))

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _tables_after(heading):
        for element in heading.find_all_next(["h2", "h3", "table"]):
            if element.name != "table":
                return
            yield element

    def _parse_table(self, table, year: int) -> list[ScraperReturn]:
        meetings = []
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True) for c in cells]
            if len(cells) < 3 or texts[0] == "Meeting":
                continue

            date_text = texts[1]
            # The cells are typed by hand, and dateutil fills any part a
            # cell leaves out from its default (today's year or day, not the
            # scraper's clock). Parsing against two different defaults and
            # requiring the same answer means a cell with no year or no day
            # is left out rather than given one.
            try:
                meeting_date = parse_date(
                    date_text, dayfirst=True, fuzzy=True, default=_DEFAULT_A
                ).date()
                complete = meeting_date == (
                    parse_date(
                        date_text, dayfirst=True, fuzzy=True, default=_DEFAULT_B
                    ).date()
                )
            except (ValueError, OverflowError):
                self.logger.warning(f"{self.council_name}: no date in {date_text!r}")
                continue
            if not complete:
                self.logger.warning(
                    f"{self.council_name}: {date_text!r} has no full date; "
                    f"leaving it out"
                )
                continue
            if meeting_date.year != year:
                self.logger.warning(
                    f"{self.council_name}: {date_text!r} filed under {year}"
                )

            papers: dict[str, str] = {}
            for cell in cells[2:]:
                for link in cell.find_all("a", href=True):
                    href = link["href"]
                    if not href.lower().endswith(".pdf"):
                        continue
                    label = link.get_text(" ", strip=True)
                    if _EXTRA.search(label):
                        continue
                    if _MINUTES.search(label):
                        kind = "minutes"
                    elif _AGENDA.search(label):
                        kind = "agenda"
                    else:
                        # "Adopted_Budget_2025_2026" beside the minutes.
                        continue
                    papers.setdefault(kind, requote_uri(urljoin(_LISTING_URL, href)))

            if not papers:
                # Scheduled, papers not up yet.
                continue
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            meetings.append(
                ScraperReturn(
                    name=self._name(texts[0]),
                    date=meeting_date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return meetings

    @staticmethod
    def _name(cell_text: str) -> str:
        name = _FINANCIAL_YEAR.sub("", cell_text).strip()
        return _NAMES.get(name, name)
