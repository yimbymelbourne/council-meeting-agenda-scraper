import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import filename_of, find_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://chrc.qld.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings/"

# Everything is on this one WordPress page, so any range is one request. Its
# sections, by h2:
#
#   "Agendas and minutes"                 the current year, a table whose rows
#                                         are a title cell and a "Download" link
#   "General council meeting archive"     earlier years, one linked title per
#                                         document, newest first
#   "Standing committee meeting archive"  the three standing committees, which
#                                         last met in March 2020
#
# robots.txt is long but lists only specific files—forms, templates and old
# media releases—and never this page; this scraper fetches nothing else.
_SECTIONS = (
    "agendas and minutes",
    "general council meeting archive",
    "standing committee meeting archive",
)

# Titles say what each document is: "Agenda – General Council Meeting – 23
# September 2026", "Unconfirmed Minutes - General Council Meeting - 23
# September 2026 + attachments V2". Each agenda also has an "index page"
# (its first pages alone), often a "Late Agenda" (a supplement), and the
# archive carries report attachments and appendices; none of those is the
# agenda. "Part 1" of a split agenda is kept, later parts are not.
_NOT_THE_PAPER = re.compile(
    r"index page|late agenda|attachment \d|^attachment|appendix|part [2-9]|"
    r"business case|ceo decision",
    re.IGNORECASE,
)
_AGENDA = re.compile(r"^agenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"^(?:(?:un)?confirmed\s+)?minutes\b", re.IGNORECASE)

# The same meeting is titled differently on its agenda and its minutes—11
# May 2026 is "Special Council Meeting" on one and "Special General Council
# Meeting" on the other—and a general and a special budget meeting can share
# a day (17 June 2026). So meetings are keyed by their kind and date, named
# after the kind.
_KINDS = (
    (re.compile(r"special\s+budget", re.IGNORECASE), "Special Budget Meeting"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special General Council Meeting"),
    (re.compile(r"post[\s-]*election", re.IGNORECASE), "Post-Election Meeting"),
    (
        re.compile(
            r"(communities|finance and infrastructure|leadership and governance)\s+standing\s+committee",
            re.IGNORECASE,
        ),
        None,
    ),
    (re.compile(r"general\s+council\s+me+t", re.IGNORECASE), "General Council Meeting"),
)


@register_scraper
class CentralHighlandsQldScraper(BaseScraper):
    def __init__(self):
        super().__init__("central_highlands_qld", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-")).strip()

    def _documents(self, soup: BeautifulSoup) -> list[tuple[str, str]]:
        """``(title, pdf_url)`` for every document in the three sections.

        In the current-year table the title is the row's first cell. In the
        archives it is the link text—once split across two links to the same
        file ("A" and "genda – General Council Meeting – 22 January 2025"),
        so a fragment with no date yet is joined to the link after it. A file
        linked twice under two full titles keeps the first: 8 March 2023's
        minutes are also linked as "8 February 2023".
        """
        documents: dict[str, str] = {}
        for heading in soup.find_all("h2"):
            if heading.get_text(" ", strip=True).lower() not in _SECTIONS:
                continue
            for element in heading.find_all_next(["h2", "a"]):
                if element.name == "h2":
                    break
                href = element.get("href") or ""
                if not filename_of(href).lower().endswith(".pdf"):
                    continue
                row = element.find_parent("tr")
                if row is not None:
                    cell = row.find("td")
                    documents.setdefault(
                        href, cell.get_text(" ", strip=True) if cell else ""
                    )
                elif href in documents:
                    if not find_date(documents[href]):
                        documents[href] += element.get_text("", strip=True)
                else:
                    documents[href] = element.get_text(" ", strip=True)
        return [(self._clean(title), href) for href, title in documents.items()]

    @staticmethod
    def _filename_date(url: str) -> Optional[datetime.date]:
        name = filename_of(url)
        numeric = re.search(r"(?<!\d)(\d{2})-(\d{2})-(20\d{2})(?!\d)", name)
        if numeric:
            try:
                return datetime.date(
                    int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1))
                )
            except ValueError:
                return None
        found = find_date(re.sub(r"[-_]+", " ", name))
        return found[0] if found else None

    @staticmethod
    def _kind(title: str) -> Optional[str]:
        for pattern, name in _KINDS:
            match = pattern.search(title)
            if match:
                return (
                    name
                    or f"{match.group(1).title().replace(' And ', ' and ')} Standing Committee Meeting"
                )
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )

        meetings: dict[tuple[str, datetime.date], dict] = {}
        for title, href in self._documents(soup):
            if _NOT_THE_PAPER.search(title):
                continue
            if _AGENDA.search(title):
                paper = "agenda"
            elif _MINUTES.search(title):
                paper = "minutes"
            else:
                continue
            # 9 September 2020's "Minutes" link is a file named
            # Redacted-Agenda-..., and it is the agenda: its cover is the
            # notice of meeting. Where the title and the filename disagree on
            # which paper it is, the filename wins.
            name_in_file = filename_of(href).lower()
            if (
                paper == "minutes"
                and "agenda" in name_in_file
                and "minute" not in name_in_file
            ):
                paper = "agenda"
            elif (
                paper == "agenda"
                and "minute" in name_in_file
                and "agenda" not in name_in_file
            ):
                paper = "minutes"
            found = find_date(title)
            kind = self._kind(title)
            if not found or not kind:
                self.logger.info(f"Central Highlands: cannot place {title!r}; skipped")
                continue
            # Where a title and its file disagree on the day, the file has
            # been right each time it was checked: "Minutes – General Council
            # Meeting – 29 January 2021" is Minutes-...-28-January-2021-....pdf,
            # and the minutes' own cover says Thursday 28 January 2021. A
            # file that differs only in the year is a typo in the file: 10
            # February 2021's agenda is Agenda-...-10-February-2020.pdf.
            date = found[0]
            named = self._filename_date(href)
            if named and (named.month, named.day) != (date.month, date.day):
                date = named
            if date.year not in wanted:
                continue
            meeting = meetings.setdefault(
                (kind, date), {"agenda": None, "minutes": None}
            )
            if meeting[paper] is None:
                meeting[paper] = href

        # 14 December 2020's agenda is a "Special General Council Meeting" and
        # its minutes a "General Council Meeting"; no other meeting sat that
        # day. When a day holds exactly two records and one is only an agenda
        # and the other only minutes, they are one meeting, named by its
        # agenda.
        by_day: dict[datetime.date, list[tuple[str, datetime.date]]] = {}
        for key in meetings:
            by_day.setdefault(key[1], []).append(key)
        for keys in by_day.values():
            if len(keys) != 2:
                continue
            first, second = (meetings[k] for k in keys)
            halves = {
                (bool(first["agenda"]), bool(first["minutes"])),
                (bool(second["agenda"]), bool(second["minutes"])),
            }
            if halves == {(True, False), (False, True)}:
                agenda_key = keys[0] if first["agenda"] else keys[1]
                minutes_key = keys[1] if agenda_key == keys[0] else keys[0]
                meetings[agenda_key]["minutes"] = meetings.pop(minutes_key)["minutes"]

        results = [
            ScraperReturn(
                name=kind,
                date=date.isoformat(),
                time=None,
                webpage_url=_LISTING_URL,
                agenda_url=docs["agenda"],
                minutes_url=docs["minutes"],
                download_url=docs["agenda"] or docs["minutes"],
            )
            for (kind, date), docs in sorted(
                meetings.items(), key=lambda kv: kv[0][1], reverse=True
            )
        ]
        if not results:
            self.logger.warning(
                f"Central Highlands: no meetings found on {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
