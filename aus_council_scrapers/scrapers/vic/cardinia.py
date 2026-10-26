"""Cardinia Shire Council (VIC).

Drupal 11, two plain HTML pages, no JavaScript needed:

- The meetings page holds four tab panels, all in the static HTML: "Most
  recent meetings" and "Past meetings" (ordinary meetings from April 2024
  on), "Additional meetings" (2019 on) and "Town Planning Committee
  meetings" (2019 to 2025).
- The archive page holds one table per year under an `h2`, ordinary meetings
  2017 to 2024.

Rows are `Meeting date | Meeting type | Agenda | Minutes | Watch`, except in
the Town Planning Committee panel, where the agenda and minutes links share
one cell. So a link's text, not its column, decides what it is. Some
meetings appear on both pages (2024, and the 1 December 2025 committee
meeting in two panels), with documents on one and an empty row on the other,
so rows are merged by date and meeting type.

Cardinia's Cloudflare challenges GitHub's runners on every client we tried
(measured 19 Oct 2026) and serves these pages to a home connection, so it
fetches through the residential proxy.
"""

import re
import string
import urllib.parse
from datetime import datetime

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.cardinia.vic.gov.au"
MEETINGS_URL = (
    f"{_BASE_URL}/about-council/council-meetings-and-minutes/agendas-and-minutes"
)
ARCHIVE_URL = (
    f"{_BASE_URL}/about-council/council-meetings-and-minutes/"
    "council-agendas-and-minutes-archive"
)

# The newest year the archive page holds. Everything after it is on the
# meetings page, so a production run for the current year skips the archive.
_ARCHIVE_LAST_YEAR = 2024

# Meeting names by tab panel, where the panel says more than the row does:
# every row in "Additional meetings" is typed plain "Council Meeting", and
# the Town Planning Committee panel has no type column at all.
_PANEL_NAMES = {
    "additional-meetings": "Additional Council Meeting",
    "town-planning-committee-meetings": "Town Planning Committee Meeting",
}

_DATE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)

# "Our next Council meeting is on Monday 19 October 2026 at 6 pm." The only
# meeting time the page states.
_NEXT_MEETING = re.compile(
    r"next Council meeting is on \w+day\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})\s+"
    r"at\s+(?P<time>\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m)",
    re.IGNORECASE,
)


def _parse_date(text: str):
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    return datetime.strptime(f"{day} {month.title()} {year}", "%d %B %Y").date()


def _panel_name(table) -> str | None:
    panel = table.find_parent("div", attrs={"role": "tabpanel"})
    if panel is None:
        return None
    # ids look like "panel-additional-meetings-3".
    slug = re.sub(r"^panel-|-\d+$", "", panel.get("id", ""))
    return _PANEL_NAMES.get(slug)


@register_scraper
class CardiniaScraper(BaseScraper):
    # Cloudflare challenges GitHub's runners on every client we tried
    # (measured 19 Oct 2026: requests with either User-Agent, Selenium with
    # and without the headless marker, Cloudflare WARP; shuck 0 of 6), and
    # serves the same pages to a home connection. See AGENTS.md, "Councils
    # that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("cardinia", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _rows(self, url: str, html: str):
        """Yield (date, name, agenda_url, minutes_url) for each dated row."""
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            raise RuntimeError(f"cardinia: no meeting tables on {url}")

        for table in tables:
            panel_name = _panel_name(table)
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells:
                    continue  # header row
                # "October 2024 | No meeting" has no day, so no meeting.
                date = _parse_date(cells[0].get_text(" ", strip=True))
                if date is None:
                    continue

                type_text = (
                    cells[1].get_text(" ", strip=True) if len(cells) > 2 else ""
                )
                name = panel_name or string.capwords(type_text) or "Council Meeting"

                agenda_url = minutes_url = None
                for link in row.find_all("a", href=True):
                    label = link.get_text(" ", strip=True).lower()
                    href = link["href"].strip()
                    if not href or "youtu" in href:
                        continue
                    absolute = urllib.parse.urljoin(url, href)
                    # Split agendas ("Part A", "Part B") are two links both
                    # labelled Agenda; the first is part A.
                    if label.startswith("agenda") and not agenda_url:
                        agenda_url = absolute
                    elif label.startswith("minutes") and not minutes_url:
                        minutes_url = absolute

                yield date, name, agenda_url, minutes_url

    def _next_meeting_time(self, html: str):
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        match = _NEXT_MEETING.search(text)
        if not match:
            return None, None
        return _parse_date(match.group("date")), match.group("time")

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()

        pages = [MEETINGS_URL]
        if min(wanted) <= _ARCHIVE_LAST_YEAR:
            pages.append(ARCHIVE_URL)

        # (date, lower-cased name) -> meeting. The first page and row to
        # supply a document wins; later rows only fill gaps.
        meetings: dict[tuple, dict] = {}
        next_date = next_time = None
        for url in pages:
            html = self.fetcher.fetch_with_requests(url)
            if url == MEETINGS_URL:
                next_date, next_time = self._next_meeting_time(html)
            for date, name, agenda_url, minutes_url in self._rows(url, html):
                if date.year not in wanted:
                    continue
                meeting = meetings.setdefault(
                    (date, name.lower()),
                    {
                        "date": date,
                        "name": name,
                        "agenda": None,
                        "minutes": None,
                        "page": url,
                    },
                )
                had_documents = bool(meeting["agenda"] or meeting["minutes"])
                if agenda_url and not meeting["agenda"]:
                    meeting["agenda"] = agenda_url
                if minutes_url and not meeting["minutes"]:
                    meeting["minutes"] = minutes_url
                # Point at the page the documents came from, not at an
                # empty row for the same meeting on the other page.
                if not had_documents and (agenda_url or minutes_url):
                    meeting["page"] = url

        results = []
        for meeting in meetings.values():
            agenda_url, minutes_url = meeting["agenda"], meeting["minutes"]
            results.append(
                ScraperReturn(
                    name=meeting["name"],
                    date=meeting["date"].isoformat(),
                    time=next_time if meeting["date"] == next_date else None,
                    webpage_url=meeting["page"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        results.sort(key=lambda r: (r.date, r.name), reverse=True)
        return results
