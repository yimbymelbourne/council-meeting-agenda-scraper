"""Tablelands Regional Council (QLD).

The meetings page lists WP Download Manager "packages" in two categories,
Council Meeting Agendas (`wpdmcategory` 2456) and Council Meeting Minutes
(2457). The WordPress REST API returns each category's packages in one
request, with the title that names the meeting and its date
("Council Meeting Agenda – 24 September 2026"), but not the files: those
are only on each package's own page, as
`/download/<slug>/?wpdmdl=<package>&ind=<file>&refresh=<token>&filename=...`.

So a meeting costs a package-page request for its agenda and another for
its minutes. Production's one year is two REST calls plus about 25 package
pages—over the ~20-request aim, and there is no cheaper route: the REST
API, the plugin's own `wpdm/search` route and the media library carry no
file lists. Packages are filtered on their REST post date before any page
is fetched, so a year never pays for another year's packages.

The emitted URL is `<package page>?wpdmdl=<package>&ind=<file>`, without
the `refresh` token. That token changes from one page load to the next;
without it the server still returns the PDF itself (checked 20 Oct 2026,
`content-type: application/pdf`), and the URL stays the same night to
night. `?wpdmdl=<package>` alone would return a zip for any package with
more than one file, which most agenda packages have.

An agenda package holds several files: the public agenda ("Agenda-Public-
24-September-2026.pdf"), an order of business ("Agenda-Listing-..."), a
"Summary Agenda", late reports and attachments. Only the public agenda is
the agenda.

Two special meetings were held on 5 August 2025, at 9:00 and 9:30am. There
is one agenda package, and one minutes package holding both sets of
minutes, the second's file named "...-commencing-9.30am". That file becomes
its own minutes-only record, "Special Council Meeting (second meeting)" at
9:30am, the naming `canning.py` uses for the same case.

The site only goes back to September 2024. robots.txt has an empty
Disallow, so the REST API is allowed.
"""

from __future__ import annotations

import datetime
import html as html_lib
import json
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.trc.qld.gov.au"
_REST_URL = f"{_BASE_URL}/wp-json/wp/v2/wpdmpro"
_AGENDA_CATEGORY = 2456
_MINUTES_CATEGORY = 2457

_MONTH_WORD = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
# "24 September 2026", "26th June 2025"; in filenames, "25-June-2026" and
# "01-July-2026".
_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+{_MONTH_WORD}[\s-]+(\d{{4}})(?!\d)", re.I
)

_FILE_LINK = re.compile(r"[?&]wpdmdl=(\d+)&ind=(\d+)")
_FILENAME_PARAM = re.compile(r"[?&]filename=([^&]+)")

_AGENDA = re.compile(r"(?<![a-z])agenda(?![a-z])", re.I)
_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])", re.I)
# In an agenda package: everything that is not the agenda.
_NOT_THE_AGENDA = re.compile(
    r"listing|summary|late|notice|attach|\bitem|report|minutes", re.I
)
_PUBLIC = re.compile(r"public", re.I)
# "V2-Agenda-public-24-July-2025", "Agenda-Public-27-November-2025-v2",
# "Agenda-Public-31-October-2024-version-2".
_VERSION = re.compile(r"(?:^|[-_.])v(?:ersion)?-?(\d+)(?=[-_.])", re.I)
_UNCONFIRMED = re.compile(r"unconfirmed", re.I)
_PART = re.compile(r"^(\d+)\.")

# "Confirmed-Minutes-Special-Meeting-5-August-2025-commencing-9.30am.pdf":
# a second meeting the same day, filed in the first one's minutes package.
_COMMENCING = re.compile(r"commencing[-_ ]+(\d{1,2})[.:](\d{2})\s*([ap]m)", re.I)

_BUDGET = re.compile(r"budget", re.I)
_SPECIAL = re.compile(r"special", re.I)


def _date_in(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text)
    if not match:
        return None
    try:
        return datetime.date(
            int(match.group(3)),
            _MONTHS.index(match.group(2).lower()) + 1,
            int(match.group(1)),
        )
    except ValueError:
        return None


def _meeting_type(text: str) -> str:
    if _BUDGET.search(text):
        return "Special Budget Meeting"
    if _SPECIAL.search(text):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class TablelandsScraper(BaseScraper):
    # Measured 20 Oct 2026 from a home IP for --years 2026: 27 requests,
    # 51-55 s at the default 2 s FETCH_DELAY (all on one host, so the
    # spacing is the cost). See the module docstring for why.
    expected_seconds = 55.0

    def __init__(self):
        super().__init__("tablelands", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _packages(self, category: int, wanted: set[int]) -> list[dict]:
        # A package is posted days before an agenda's meeting and days after
        # a minutes' one, so a month's margin either side of the wanted
        # years catches every package that could belong to them.
        after = datetime.date(min(wanted) - 1, 12, 1)
        before = datetime.date(max(wanted) + 1, 2, 1)
        packages: list[dict] = []
        for page in range(1, 20):
            query = urllib.parse.urlencode(
                {
                    "wpdmcategory": category,
                    "per_page": 100,
                    "page": page,
                    "after": f"{after.isoformat()}T00:00:00",
                    "before": f"{before.isoformat()}T00:00:00",
                    "_fields": "id,date,link,title",
                }
            )
            batch = json.loads(self.fetcher.fetch_with_requests(f"{_REST_URL}?{query}"))
            packages.extend(batch)
            if len(batch) < 100:
                break
        return packages

    @staticmethod
    def _files(page_html: str) -> list[tuple[str, str]]:
        """(filename, stable URL) for each file in a package, in page order."""
        soup = BeautifulSoup(page_html, "html.parser")
        files: list[tuple[str, str]] = []
        seen = set()
        for link in soup.find_all("a", href=True):
            href = html_lib.unescape(link["href"])
            match = _FILE_LINK.search(href)
            if not match or match.group(2) in seen:
                continue
            seen.add(match.group(2))
            name_match = _FILENAME_PARAM.search(href)
            name = urllib.parse.unquote(name_match.group(1)) if name_match else ""
            base = href.split("?", 1)[0]
            files.append((name, f"{base}?wpdmdl={match.group(1)}&ind={match.group(2)}"))
        return files

    @staticmethod
    def _pick_agenda(files: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
        candidates = [
            (index, name, url)
            for index, (name, url) in enumerate(files)
            if _AGENDA.search(name) and not _NOT_THE_AGENDA.search(name)
        ]
        if not candidates:
            return None

        def rank(candidate):
            index, name, _ = candidate
            version = _VERSION.search(name)
            # The public copy first, then the highest revision, then page order.
            return (
                not _PUBLIC.search(name),
                -(int(version.group(1)) if version else 1),
                index,
            )

        _, name, url = min(candidates, key=rank)
        return name, url

    @staticmethod
    def _pick_minutes(files: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
        candidates = [
            (index, name, url)
            for index, (name, url) in enumerate(files)
            if _MINUTES.search(name)
        ]
        if not candidates:
            return None

        def rank(candidate):
            index, name, _ = candidate
            part = _PART.match(name)
            # Confirmed before unconfirmed; "1.-Minutes" before "2.-Minutes";
            # a later same-day meeting's "...-commencing-9.30am" file last,
            # since it is that meeting's, not this one's.
            return (
                bool(_UNCONFIRMED.search(name)),
                bool(_COMMENCING.search(name)),
                int(part.group(1)) if part else 0,
                index,
            )

        _, name, url = min(candidates, key=rank)
        return name, url

    def _read(
        self, kind: str, packages: list[dict], wanted: set[int], meetings: dict
    ) -> None:
        for package in packages:
            title = html_lib.unescape(package["title"]["rendered"])
            if re.match(r"\s*notice of", title, re.I):
                continue  # a notice package holds only the notice
            if kind == "minutes" and not (
                _MINUTES.search(title) or re.search(r"meeting", title, re.I)
            ):
                continue  # draft plans and local laws filed with the minutes
            date = _date_in(title)
            if date is not None and date.year not in wanted:
                continue

            files = self._files(self.fetcher.fetch_with_requests(package["link"]))
            chosen = (
                self._pick_agenda(files)
                if kind == "agenda"
                else self._pick_minutes(files)
            )
            if chosen is None:
                continue
            file_name, url = chosen
            # "Special (Budget) Meeting – Agenda" names no date; its file does.
            date = date or _date_in(file_name)
            if date is None:
                self.logger.warning(
                    f"No meeting date in package {title!r} or its file {file_name!r}"
                )
                continue
            if date.year not in wanted:
                continue

            key = (_meeting_type(f"{title} {file_name}"), date)
            papers = meetings.setdefault(key, {"webpage": package["link"]})
            existing = papers.get(kind)
            # Two minutes packages for one meeting (27 August 2026 has an
            # unconfirmed and a confirmed one): confirmed wins.
            if existing is None or (
                _UNCONFIRMED.search(existing[0]) and not _UNCONFIRMED.search(file_name)
            ):
                papers[kind] = (file_name, url)
                if kind == "agenda":
                    papers["webpage"] = package["link"]
            if kind == "minutes" and not _COMMENCING.search(file_name):
                self._second_meetings(key, files, file_name, package, meetings)

    def _second_meetings(
        self, key, files: list[tuple[str, str]], chosen: str, package, meetings
    ) -> None:
        """A later same-day meeting's minutes, filed beside the first's."""
        name, date = key
        for file_name, url in files:
            match = _COMMENCING.search(file_name)
            if (
                file_name == chosen
                or not match
                or not _MINUTES.search(file_name)
                or _UNCONFIRMED.search(file_name)
            ):
                continue
            hour, minute, half = match.groups()
            self.logger.info(
                f"{date}: {file_name!r} is a second {name} at {hour}:{minute}{half}"
            )
            meetings.setdefault(
                (f"{name} (second meeting)", date),
                {
                    "webpage": package["link"],
                    "time": f"{int(hour)}:{minute}{half.lower()}",
                    "minutes": (file_name, url),
                },
            )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        meetings: dict[tuple[str, datetime.date], dict] = {}
        agenda_packages = self._packages(_AGENDA_CATEGORY, wanted)
        minutes_packages = self._packages(_MINUTES_CATEGORY, wanted)
        self._read("agenda", agenda_packages, wanted, meetings)
        self._read("minutes", minutes_packages, wanted, meetings)

        results = []
        for (name, date), papers in sorted(
            meetings.items(), key=lambda kv: (kv[0][1], kv[0][0])
        ):
            agenda_url = papers["agenda"][1] if "agenda" in papers else None
            minutes_url = papers["minutes"][1] if "minutes" in papers else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=papers.get("time"),
                    webpage_url=papers["webpage"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            message = (
                f"{self.council_name}: no meetings with papers in {sorted(wanted)}"
            )
            # Nothing before September 2024 is online, so only a year since
            # then counts as one that should have something in it.
            if max(wanted) >= 2025 and clock.today() - datetime.date(
                max(min(wanted), 2025), 1, 1
            ) > datetime.timedelta(days=90):
                raise RuntimeError(
                    message + "; the packages have probably changed shape"
                )
            self.logger.warning(message)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
