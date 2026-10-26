"""Bayside City Council (VIC).

Two Drupal listing pages, one for agendas and one for minutes, each a run of
month headings over lists of PDF links. Every link's text starts with the
meeting date and ends with what the document is—"20 October 2026 Council
Meeting Agenda"—so the text, not the position, decides what a link is. The
agendas page also carries "Requests to be Heard", late agendas and item
attachments under the same headings, which the previous version of this
scraper took for agendas.

The council refuses GitHub's runners outright (403 as a browser, connection
reset when identifying, measured 19 Oct 2026) and serves the same pages to a
home connection, so it fetches through the residential proxy.
"""

import re
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.bayside.vic.gov.au"
AGENDAS_URL = f"{_BASE_URL}/council/meetings-agendas-and-minutes/council-meeting-agendas"
MINUTES_URL = f"{_BASE_URL}/council/meetings-agendas-and-minutes/council-minutes"

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)

# "20 October 2026 ...", "16 September 2025 - ...", and the two multi-day
# forms the council uses: "15 and 16 June 2022" and "31 March and 14 April
# 2021". A multi-day meeting is dated by its first day.
_LEADING_DATE = re.compile(
    rf"^(?P<day>\d{{1,2}})(?:\s+(?P<month>{_MONTHS}))?"
    rf"(?:\s+and\s+\d{{1,2}}\s+(?P<later_month>{_MONTHS}))?"
    rf"\s+(?P<year>\d{{4}})\s*-?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

# What is left after the date must end in "Agenda" or "Minutes". That is what
# rules out "- Requests to be Heard", "- Written Statements" and "- Item 10.1
# - Attachment 3 - ...", which sit under the same month headings.
_DOCUMENT = re.compile(
    r"^(?P<name>.*?)\s*(?P<late>\(Late\)|\bLate)?\s*(?P<kind>Agenda|Minutes)\)?$",
    re.IGNORECASE,
)

# Words that differ between an agenda's title and its minutes' title for the
# same meeting: "Special Council Meeting" against "Special Meeting of
# Council", "... Delegated Committee Meeting Agenda" against "... Delegated
# Committee Minutes".
_NAME_NOISE = {"meeting", "of", "the"}


def _clean_text(text: str) -> str:
    text = text.replace("​", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\[[^\]]*\]$", "", text)  # "[PDF 69.60 MB]"
    text = re.sub(r"\.pdf$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _name_key(name: str) -> frozenset:
    return frozenset(w for w in name.lower().split() if w not in _NAME_NOISE)


def _parse_link(text: str):
    """(date, name, kind, is_late) for an agenda or minutes link, else None."""
    match = _LEADING_DATE.match(_clean_text(text))
    if not match:
        return None
    document = _DOCUMENT.match(match.group("rest"))
    if not document:
        return None
    month = match.group("month") or match.group("later_month")
    if not month:
        return None
    date = datetime.strptime(
        f"{match.group('day')} {month.title()} {match.group('year')}", "%d %B %Y"
    ).date()
    name = document.group("name").strip(" -") or "Council Meeting"
    return date, name, document.group("kind").lower(), bool(document.group("late"))


@register_scraper
class BaysideVicScraper(BaseScraper):
    # Refuses GitHub's runners whatever we send: 403 as a browser, connection
    # reset when identifying (measured 19 Oct 2026). Serves the same pages to
    # a home connection. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("bayside_vic", "VIC", _BASE_URL)
        self.default_location = "Civic Centre Precinct Boxshall Street, Brighton"
        self.default_time = "18:30"

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _documents(self, url: str):
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        body = soup.find("div", class_="page__body")
        if body is None:
            raise RuntimeError(f"bayside_vic: no page__body on {url}")
        for link in body.find_all("a", href=True):
            parsed = _parse_link(link.get_text(" ", strip=True))
            if parsed:
                yield (*parsed, urllib.parse.urljoin(url, link["href"]))

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()

        # (date, name key) -> meeting. Both pages are newest first, and the
        # first link seen for a slot wins.
        meetings: dict[tuple, dict] = {}

        for date, name, kind, late, url in self._documents(AGENDAS_URL):
            if kind != "agenda" or date.year not in wanted:
                continue
            meeting = meetings.setdefault(
                (date, _name_key(name)),
                {"date": date, "name": name, "agenda": None, "late": None},
            )
            # A late agenda is a supplement to the main one, so it stands in
            # only when the main agenda is missing.
            slot = "late" if late else "agenda"
            meeting[slot] = meeting[slot] or url

        for date, name, kind, late, url in self._documents(MINUTES_URL):
            if kind != "minutes" or date.year not in wanted:
                continue
            meeting = meetings.get((date, _name_key(name)))
            if meeting is None:
                # Titles drift between the two pages ("Special Council
                # Meeting" against "Special Meeting of Council"), so fall
                # back to the date when it identifies one meeting.
                same_day = [m for (d, _), m in meetings.items() if d == date]
                if len(same_day) == 1 and not same_day[0].get("minutes"):
                    meeting = same_day[0]
            if meeting is None:
                meeting = meetings.setdefault(
                    (date, _name_key(name)),
                    {"date": date, "name": name, "agenda": None, "late": None},
                )
            meeting["minutes"] = meeting.get("minutes") or url

        results = []
        for meeting in meetings.values():
            agenda_url = meeting["agenda"] or meeting["late"]
            minutes_url = meeting.get("minutes")
            results.append(
                ScraperReturn(
                    name=meeting["name"],
                    date=meeting["date"].isoformat(),
                    time=None,
                    webpage_url=AGENDAS_URL if agenda_url else MINUTES_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        results.sort(key=lambda r: (r.date, r.name), reverse=True)
        return results
