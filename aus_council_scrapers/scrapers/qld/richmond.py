import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper

# Everything before the move to Resolve: a table of agendas per year (2023 to
# June 2025) and a table of minutes per year (2024 to June 2025), all direct
# PDF links, in one request. The council posted no 2023 minutes here, so the
# 2023 meetings have their agenda only.
ARCHIVE = "https://www.richmond.qld.gov.au/archive-agendas-minutes"


@register_scraper
class RichmondShireScraper(ResolveScraper):
    # Richmond Shire, QLD. The Resolve tenant "richmond" is this council,
    # not Richmond Valley (NSW): www.richmond.qld.gov.au/current-agendas-minutes
    # frames richmond.resolve.red/web/. The tenant starts with the 15 July
    # 2025 meeting; earlier papers are on the council's archive page, read by
    # `other_meetings`. Production asks for the current year only, so the
    # archive costs nothing there.
    tenant = "richmond"
    resolve_from = datetime.date(2025, 7, 15)

    # "Council" is the tenant's only type, used for ordinary and special
    # (budget) meetings alike. Naming it keeps a committee the council
    # starts publishing here from adding a request per meeting unasked.
    meeting_types = re.compile(r"^Council$")

    # The base class turns "Special ..." in the event name into "Special
    # Council Meeting" from this.
    meeting_type_names = {"Council": "Ordinary Council Meeting"}

    def __init__(self):
        super().__init__("richmond", "QLD")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = {year for year in self.before_resolve(wanted) if year >= EARLIEST_YEAR}
        if not years:
            return []
        meetings = self._archive(self.fetcher.fetch_with_requests(ARCHIVE))
        if not meetings:
            raise RuntimeError(
                f"{self.council_name}: no past agendas or minutes on {ARCHIVE}"
            )
        return [
            meeting
            for meeting in meetings
            if int(meeting.date[:4]) in years
            and datetime.date.fromisoformat(meeting.date) < self.resolve_from
        ]

    def _archive(self, html: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        papers: dict[tuple[str, str], dict[str, str]] = {}
        kind = year = None
        # The page is two headed tables, "Agenda" then "Minutes", each a run
        # of rows: a year on its own, then that year's meetings.
        for element in soup.find_all(["h2", "tr"]):
            text = element.get_text(" ", strip=True)
            if element.name == "h2":
                kind = {"agenda": "agenda", "minutes": "minutes"}.get(text.lower())
                continue
            if not kind:
                continue
            cells = element.find_all(["td", "th"])
            label = cells[0].get_text(" ", strip=True) if cells else ""
            if re.fullmatch(r"(19|20)\d{2}", label):
                year = int(label)
                continue
            if not year:
                continue
            for link in element.find_all("a", href=True):
                if not link["href"].lower().endswith(".pdf"):
                    continue
                # Agenda rows have three columns: "Ordinary" (the agenda),
                # "Late" (late items, a supplement) and "Confidential" (a
                # table of contents of the closed reports). Only the first is
                # the agenda. Minutes rows hold one link each.
                if kind == "agenda" and link.get_text(strip=True) != "Ordinary":
                    continue
                url = urljoin(ARCHIVE, link["href"])
                date = self._meeting_date(year, label, url)
                if not date:
                    continue
                papers.setdefault((date, _name(label)), {})[kind] = url

        return [
            ScraperReturn(
                name=name,
                date=date,
                time=None,
                webpage_url=ARCHIVE,
                agenda_url=found.get("agenda"),
                minutes_url=found.get("minutes"),
                download_url=found.get("agenda") or found.get("minutes"),
            )
            for (date, name), found in sorted(papers.items())
        ]

    def _meeting_date(self, year: int, label: str, url: str) -> Optional[str]:
        """The meeting's date: the table's year and the row's month, with the
        day from the row ("16 July (Budget)") or else from the file's
        YYYYMMDD stamp. The stamp alone is not trusted, because it is
        sometimes the drafting date or the wrong year; see `_STAMP_DATES`."""
        path = urlparse(url).path
        if path in _STAMP_DATES:
            return _STAMP_DATES[path]
        month_match = _MONTH.search(label)
        if not month_match:
            self.logger.warning(f"{self.council_name}: no month in row {label!r}")
            return None
        month = _MONTHS.index(month_match.group(1).lower()) + 1
        day_match = re.search(rf"\b(\d{{1,2}})\s+{month_match.group(1)}", label)
        if day_match:
            day = int(day_match.group(1))
        else:
            stamp = re.search(r"(20\d{2})(\d{2})(\d{2})", path.rsplit("/", 1)[-1])
            # A stamp whose month is not the row's is a drafting date, not
            # the meeting's; leave the paper out rather than guess its day.
            if not stamp or int(stamp.group(2)) != month:
                self.logger.warning(
                    f"{self.council_name}: cannot date {url} in row {label!r}"
                )
                return None
            day = int(stamp.group(3))
        return datetime.date(year, month, day).isoformat()


_MONTHS = [
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
]  # fmt: skip
_MONTH = re.compile(rf"\b({'|'.join(_MONTHS)})\b", re.IGNORECASE)

# Files whose YYYYMMDD stamp is not the meeting's date, checked against the
# PDF's own cover and, where there are minutes, against those.
_STAMP_DATES = {
    # Stamped 4 March; the agenda and minutes are for Thursday 14 March 2024.
    "/images/Agenda/2024/20240304_Agenda.pdf": "2024-03-14",
    # Stamped 25 June, filed as "July - Budget"; the agenda and minutes are
    # for the Special Meeting (Budget) on Tuesday 16 July 2024.
    "/images/Agenda/2024/20240625_Budget_Agenda_-_July.pdf": "2024-07-16",
}
# Not corrected: the March 2025 agenda is stamped 20240318 under the 2025
# heading, which the table's year already fixes. The November 2023 agenda's
# cover says 14 November, but the late agendas, the confidential contents
# and the December agenda's confirmation of minutes all say 21 November,
# the date its stamp gives.


def _name(label: str) -> str:
    # The council's own names, matching what the Resolve tenant emits for
    # the same kinds of meeting from July 2025: a budget meeting is a
    # "Special Meeting (Budget)" on its papers.
    if re.search(r"budget|special", label, re.IGNORECASE):
        return "Special Council Meeting"
    if re.search(r"post.election", label, re.IGNORECASE):
        return "Post-Election Meeting"
    return "Ordinary Council Meeting"
