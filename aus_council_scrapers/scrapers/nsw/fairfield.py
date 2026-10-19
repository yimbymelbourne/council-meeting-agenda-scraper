import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

# The council's Business Papers page is only an OpenCities wrapper around an
# iframe; the papers themselves live in this small PHP app. It is a plain
# <form method="post"> with a year and a month dropdown, and one POST per year
# with month=00 ("All Months") returns that year's every meeting as a table.
#
# month=00 has to be sent explicitly: on a bare GET the form defaults to the
# current year *and the current month*, so it shows a few weeks, not the year.
_APP_URL = "https://bpweb.fairfieldcity.nsw.gov.au/fccbps/"

_NO_PAPERS = "No papers published for this period"

# The table mixes real meetings with rows that are only extra documents for
# a meeting listed elsewhere, and none of those may be stored as an agenda:
#
# - "Services/Outcomes Supplementary Reports - Report by Chairman" rows carry
#   the committee chair's report to the Ordinary Council meeting that night.
#   They have no minutes and are not a meeting of their own.
# - "<Committee> - Supplementary" rows are usually a supplementary agenda
#   (filename ..._COM_AT_SUP...) next to the committee's main row.
#
# The filename is the reliable signal, not the label: on 1 June 2026 the
# council labelled the Traffic Committee's *only* row "- Supplementary", yet
# it holds the main agenda (TRA_01062026_COM_AT_PUBLIC.pdf) and the minutes.
_CHAIRMANS_REPORT = re.compile(r"supplementary reports", re.IGNORECASE)
_SUPPLEMENTARY_FILE = re.compile(r"(?:^|[_\-\s])SUP(?:$|[_\-\s.])", re.IGNORECASE)
_SUPPLEMENTARY_LABEL = re.compile(r"\s*-\s*supplementary\s*$", re.IGNORECASE)

# The table has six columns (Meeting Date | Committee | Agendas | Minutes |
# Additional attachments | Audio/Video - Meeting). They are located by
# header text, not position: if the council inserted or reordered a column,
# reading by index would quietly store attachments or minutes as the agenda.
_COLUMNS = {
    "date": "meeting date",
    "committee": "committee",
    "agenda": "agendas",
    "minutes": "minutes",
}


def _document_url(cell) -> str | None:
    link = cell.find("a", href=True) if cell else None
    if not link:
        return None
    # Filenames are hand-typed and some contain spaces
    # ("CSC_06102026_MIN - Public.PDF"); requote_uri escapes those without
    # double-escaping anything already encoded.
    return requote_uri(urljoin(_APP_URL, link["href"].strip()))


def _filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _meeting_name(label: str) -> str:
    # "Ordinary Council" reads as a body, not a meeting; the committees
    # ("Outcomes Committee") already read as one.
    if label.lower().endswith("council"):
        return f"{label} Meeting"
    return label


@register_scraper
class FairfieldScraper(BaseScraper):
    def __init__(self):
        super().__init__("fairfield", "NSW", "https://www.fairfieldcity.nsw.gov.au")

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _scrape_year(self, year: int) -> list[tuple[ScraperReturn, bool]]:
        # A fetch failure is left to raise. Production asks for one year, so
        # catching it here would turn a timeout into "0 meetings" that the
        # ingest counts as a success.
        html = self.fetcher.fetch_with_requests(
            _APP_URL,
            method="POST",
            data={"year": str(year), "month": "00", "findBtn": "Find"},
        )
        soup = BeautifulSoup(html, "html.parser")

        header = soup.find("tr", class_="bpsRowHeader")
        if header is None:
            if _NO_PAPERS in html:
                # Normal for a year the council has not started publishing.
                # For a year that should have papers it means the app has
                # changed or lost its history, so say so.
                log = (
                    self.logger.info
                    if year > clock.current_year()
                    else self.logger.warning
                )
                log(f"{self.council_name}: no papers published for {year}")
                return []
            raise RuntimeError(
                f"{self.council_name}: no meeting table and no 'no papers' "
                f"notice in the {year} page; the app's layout has changed"
            )

        headings = [
            re.sub(r"\s+", " ", th.get_text(" ", strip=True)).lower()
            for th in header.find_all("th")
        ]
        missing = [text for text in _COLUMNS.values() if text not in headings]
        if missing:
            raise RuntimeError(
                f"{self.council_name}: the {year} table has no {missing} "
                f"column (headings: {headings}); the app's layout has changed"
            )
        col = {key: headings.index(text) for key, text in _COLUMNS.items()}
        width = max(col.values()) + 1

        rows: list[tuple[ScraperReturn, bool]] = []
        for tr in header.find_next_siblings("tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) < width:
                continue

            try:
                date = datetime.datetime.strptime(
                    cells[col["date"]].get_text(strip=True), "%d/%m/%Y"
                ).date()
            except ValueError:
                self.logger.warning(
                    f"{self.council_name}: unparseable date "
                    f"{cells[col['date']].get_text(strip=True)!r} in {year}"
                )
                continue

            label = re.sub(
                r"\s+", " ", cells[col["committee"]].get_text(" ", strip=True)
            )
            agenda_url = _document_url(cells[col["agenda"]])
            minutes_url = _document_url(cells[col["minutes"]])

            if _CHAIRMANS_REPORT.search(label):
                continue
            if agenda_url and _SUPPLEMENTARY_FILE.search(_filename(agenda_url)):
                continue
            if not agenda_url and not minutes_url:
                continue

            supplementary_label = bool(_SUPPLEMENTARY_LABEL.search(label))
            label = _SUPPLEMENTARY_LABEL.sub("", label)

            rows.append(
                (
                    ScraperReturn(
                        name=_meeting_name(label),
                        # The page writes dd/mm/yyyy, which dateutil would
                        # read month-first; emit ISO so nothing downstream
                        # has to guess.
                        date=date.isoformat(),
                        time=None,
                        webpage_url=_APP_URL,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    ),
                    supplementary_label,
                )
            )
        return rows

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        rows: list[tuple[ScraperReturn, bool]] = []
        for year in wanted:
            rows.extend(self._scrape_year(year))

        # A "- Supplementary" row that survived the filename check is kept as
        # the meeting itself—unless the same committee also has an
        # unlabelled row that night, which is then the real one.
        plain = {(r.name, r.date) for r, supplementary in rows if not supplementary}
        results = [
            r
            for r, supplementary in rows
            if not (supplementary and (r.name, r.date) in plain)
        ]

        if not results:
            # The one legitimate empty answer: production asks only for the
            # current year, and Fairfield's first meeting is usually in
            # February, so for most of January the app truthfully says "No
            # papers published". Anything else empty means the source broke.
            if all(year >= clock.current_year() for year in wanted):
                self.logger.warning(
                    f"{self.council_name}: no papers published yet for {wanted}"
                )
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
