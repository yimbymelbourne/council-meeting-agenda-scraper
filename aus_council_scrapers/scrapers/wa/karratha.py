"""City of Karratha (WA).

A Drupal view lists one row per meeting, newest first, 20 to a page, with
the meeting's documents linked straight to `/sites/default/files/` PDFs. Its
exposed filter takes a date range on the meeting's date field
(`field_date_range_value[min]` / `[max]`, ISO dates), so one query bounds
what gets fetched: production's single year is one or two listing pages.

**The date is the hard part.** Row titles give the month only ("Ordinary
Council Meeting - September 2026"); a few special meetings give the day.
The day comes from the papers' filenames, which the council has prefixed
with the meeting date since 2020 in one of two spellings:
`20260928_ordinary_council_meeting_agenda_0.pdf` or
`200817 OCM AGENDA AUGUST 2020.pdf`. Minutes are preferred to the agenda as
a witness, because they are written after the meeting and record when it
happened: the April 2022 agenda is filed `220412 OCM AGENDA` for a meeting
the minutes (`220426 OCM MINUTES 26 APRIL 2022`) put on 26 April.

The meeting page each row links to also shows a date, but it cannot be
trusted on its own: for meetings migrated into the site in 2022 it is often
the upload time (the July 2022 special meeting's page says 14 Oct 2022,
7:16pm). It is fetched only for a meeting none of whose papers carry a
date, and used only when it falls in the month the title names. A meeting
with no day from any source is left out and logged rather than given an
invented one.

Only Council meetings (ordinary and special) are read. Public Briefing
agendas and their attachment zips share each ordinary meeting's row and are
not its agenda; the Audit, Risk and Improvement Committee and Annual
Electors' Meetings have rows of their own and are skipped.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.karratha.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings/agendas-and-minutes"

# Twenty rows a page; a whole history since 2020 is about seven pages.
_MAX_PAGES = 30

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}
_MONTH_WORD = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
# Digit lookarounds rather than \b, because filenames join words with
# underscores ("special_council_meeting_-_8_july_2026_-_minutes") and an
# underscore is a word character.
_FULL_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s_,-]+{_MONTH_WORD}[\s_,-]+(\d{{4}})(?!\d)",
    re.I,
)
_MONTH_YEAR = re.compile(rf"\b{_MONTH_WORD}\s+(\d{{4}})\b", re.I)
# The filename's leading date. Eight digits must start "20" to be read as
# yyyymmdd, which keeps a stray ddmmyyyy ("27032023_ocm_march_agenda") from
# being misread; six digits are yymmdd.
_FILE_PREFIX = re.compile(r"^(20\d{6}|\d{6})(?=[\s_.-])")

_COUNCIL_MEETING = re.compile(r"\bcouncil meeting\b", re.I)
_TITLE_SPLIT = re.compile(r"\s+[-–—]\s+")

_AGENDA = re.compile(r"(?<![a-z])agenda(?![a-z])", re.I)
_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])", re.I)
# Papers that share a meeting's row and are not its agenda or minutes. The
# filename counts as much as the label: in 2024 the briefing agenda was
# labelled "Ordinary Council Meeting – September 2024 – Agenda" and filed as
# `20240909_public_briefing_session_agenda.pdf`.
_NOT_THE_PAPER = re.compile(
    r"briefing|attach|late[\s_-]*item|notice|question|presentation", re.I
)

# A paper filed under a date this far from the meeting's is another
# meeting's: the March 2022 row links `220228 OCM AGENDA FEBRUARY 2022.pdf`.
_MISFILED_DAYS = 21


def _month_number(word: str) -> int:
    return _MONTHS[word[:3].lower()]


def _filename(url: str) -> str:
    name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    # Some 2021-2022 uploads are percent-encoded twice ("220426%2520OCM...").
    return urllib.parse.unquote(urllib.parse.unquote(name))


def _date_in_filename(url: str) -> Optional[datetime.date]:
    name = _filename(url)
    match = _FILE_PREFIX.match(name)
    if match:
        digits = match.group(1)
        try:
            if len(digits) == 8:
                return datetime.date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
            return datetime.date(
                2000 + int(digits[:2]), int(digits[2:4]), int(digits[4:])
            )
        except ValueError:
            pass
    match = _FULL_DATE.search(name)
    if match:
        try:
            return datetime.date(
                int(match.group(3)), _month_number(match.group(2)), int(match.group(1))
            )
        except ValueError:
            pass
    return None


@register_scraper
class KarrathaScraper(BaseScraper):
    def __init__(self):
        super().__init__("karratha", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page_url(self, first: datetime.date, last: datetime.date, page: int) -> str:
        query = {
            "field_date_range_value[min]": first.isoformat(),
            "field_date_range_value[max]": last.isoformat(),
        }
        if page:
            query["page"] = str(page)
        return f"{_LISTING_URL}?{urllib.parse.urlencode(query)}"

    @staticmethod
    def _rows(soup: BeautifulSoup):
        # The page nests the whole view in an outer `.views-row`; the meeting
        # rows are the ones with a title and a documents field of their own.
        for row in soup.select("div.views-row"):
            if row.select("div.views-row"):
                continue
            title = row.select_one(".views-field-title a[href]")
            documents = row.select_one(".views-field-field-documents")
            if title and documents:
                yield title, documents

    @staticmethod
    def _pick(
        candidates: list[tuple[str, str]], preferred: re.Pattern
    ) -> Optional[str]:
        for label, url in candidates:
            if preferred.search(f"{label} {_filename(url)}"):
                return url
        return candidates[0][1] if candidates else None

    def _papers(self, documents) -> tuple[Optional[str], Optional[str]]:
        agendas: list[tuple[str, str]] = []
        minutes: list[tuple[str, str]] = []
        for link in documents.find_all("a", href=True):
            url = urllib.parse.urljoin(_BASE_URL, link["href"].strip())
            if not urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
                continue  # attachment zips
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if _NOT_THE_PAPER.search(f"{label} {_filename(url)}"):
                continue
            if _MINUTES.search(label):
                minutes.append((label, url))
            elif _AGENDA.search(label):
                agendas.append((label, url))
        # After the public briefing the council posts an "Updated Agenda" for
        # the meeting itself, and after the next meeting "Confirmed Minutes";
        # either replaces the earlier paper when both are listed.
        return (
            self._pick(agendas, re.compile(r"updated", re.I)),
            self._pick(minutes, re.compile(r"confirm", re.I)),
        )

    def _node_date(self, url: str, month: tuple[int, int]) -> Optional[datetime.date]:
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        stamp = soup.find("time")
        match = _FULL_DATE.search(stamp.get_text(" ", strip=True)) if stamp else None
        if not match:
            return None
        date = datetime.date(
            int(match.group(3)), _month_number(match.group(2)), int(match.group(1))
        )
        if (date.year, date.month) != month:
            # The page's date is the upload time, not the meeting's.
            return None
        return date

    def _meeting_date(
        self, title: str, node_url: str, agenda_url, minutes_url
    ) -> Optional[datetime.date]:
        match = _FULL_DATE.search(title)
        if match:
            return datetime.date(
                int(match.group(3)), _month_number(match.group(2)), int(match.group(1))
            )
        match = _MONTH_YEAR.search(title)
        if not match:
            return None
        month = (int(match.group(2)), _month_number(match.group(1)))
        middle = datetime.date(month[0], month[1], 15)

        for url in (minutes_url, agenda_url):
            date = _date_in_filename(url) if url else None
            # A paper's date is believed only near the month the title gives.
            # The July 2022 special meeting's papers are both dated 16 August
            # 2022 ("..._special_council_meeting_agenda_august_2022.pdf"), so
            # the next month counts too.
            if date and abs((date - middle).days) <= 50:
                return date
        return self._node_date(node_url, month)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        # A month either side, so a meeting whose papers date it into a
        # neighbouring year (late December, early January) is still listed.
        first = datetime.date(min(wanted) - 1, 12, 1)
        last = datetime.date(max(wanted) + 1, 1, 31)

        results: list[ScraperReturn] = []
        seen_nodes: set[str] = set()
        undated: list[str] = []

        for page in range(_MAX_PAGES):
            soup = BeautifulSoup(
                self.fetcher.fetch_with_requests(self._page_url(first, last, page)),
                "html.parser",
            )
            rows = list(self._rows(soup))
            if page == 0 and not rows:
                raise RuntimeError(
                    f"{_LISTING_URL} listed no meetings for {first}..{last}; the "
                    f"view markup has probably changed"
                )

            for title_link, documents in rows:
                title = re.sub(r"\s+", " ", title_link.get_text(" ", strip=True))
                node_url = urllib.parse.urljoin(_BASE_URL, title_link["href"])
                if node_url in seen_nodes:
                    continue
                seen_nodes.add(node_url)

                name = _TITLE_SPLIT.split(title, maxsplit=1)[0].strip()
                if not _COUNCIL_MEETING.search(name):
                    continue  # ARIC, Annual Electors' Meeting

                agenda_url, minutes_url = self._papers(documents)
                if not (agenda_url or minutes_url):
                    # Most often next month's meeting, listed with only its
                    # briefing agenda so far.
                    continue

                date = self._meeting_date(title, node_url, agenda_url, minutes_url)
                if date is None:
                    undated.append(title)
                    continue
                if date.year not in wanted:
                    continue

                for field_name, url in (
                    ("agenda", agenda_url),
                    ("minutes", minutes_url),
                ):
                    filed = _date_in_filename(url) if url else None
                    if (
                        filed
                        and abs((filed - date).days) > _MISFILED_DAYS
                        and abs((filed - date).days) < 400
                    ):
                        self.logger.warning(
                            f"{title}: the {field_name} link {_filename(url)!r} is "
                            f"filed under {filed}, not {date}; dropped as another "
                            f"meeting's paper"
                        )
                        if field_name == "agenda":
                            agenda_url = None
                        else:
                            minutes_url = None
                if not (agenda_url or minutes_url):
                    continue

                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=node_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

            if not soup.select_one("li.pager__item--next a[href]"):
                break
        else:
            self.logger.warning(f"Stopped at the {_MAX_PAGES}-page cap")

        if undated:
            self.logger.warning(
                f"Left out {len(undated)} meeting(s) dated to the month only, with "
                f"no day in any paper or on the meeting page: {undated}"
            )
        if not results:
            message = f"{self.council_name}: no Council meetings with papers in {sorted(wanted)}"
            # Council meets monthly; three months into a year with nothing
            # means the row or document markup has changed.
            if clock.today() - datetime.date(min(wanted), 1, 1) > datetime.timedelta(
                days=90
            ):
                raise RuntimeError(message)
            self.logger.warning(message)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
