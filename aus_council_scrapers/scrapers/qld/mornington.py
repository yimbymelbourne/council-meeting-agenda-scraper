import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_LISTING_URL = "https://www.mornington.qld.gov.au/agendas-minutes/"

# Mornington Shire (Gununa, Mornington Island) puts every agenda and set of
# minutes since 2018 on this one WordPress page, in Divi toggles titled by
# year (plus one titled "Unknown"), each a list of links straight to the
# PDFs. One request covers the whole history.
#
# The link text is typed by hand and is the only place the meeting is named,
# in several shapes: "MSC Ordinary Council Meeting Agenda 30 September 2026",
# "2025 10 December Ordinary Council Meeting Agenda", "24 Sept 2025 ...",
# "2020 09 Dec ...", "... Unconfirmed Minutes 30 September" (no year, in the
# "Unknown" toggle). Only Council meetings are published, ordinary and
# special, so the name is one of those two.

_MONTH = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})[\s_-]+" + _MONTH + r"\b", re.IGNORECASE)
_MONTH_ONLY = re.compile(r"\b" + _MONTH + r"\b", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

_MINUTES = re.compile(r"min(?:utes|tues|untes)", re.IGNORECASE)
_AGENDA = re.compile(r"agenda|notice of special meeting", re.IGNORECASE)
# Late reports and attachments are extra papers beside the agenda. The 16
# June 2021 "Agenda" link is itself the attachments file, so the filename
# is checked as well as the label. "Pt2".."Pt4" are the rest of a split
# agenda whose first part is the agenda.
_EXTRA = re.compile(
    r"(?<![a-z])late|attach|separate|seperate|\bpt\s*[2-9]\b|_pt[2-9]\b", re.IGNORECASE
)
_UNCONFIRMED = re.compile(r"unco?n?firmed", re.IGNORECASE)

# Papers whose label and filename both give the wrong day, found by reading
# the PDFs. Keyed by filename; the value is the meeting date the PDF states.
_MISDATED = {
    # "2021 9 September Special Council Meeting Minutes" are the minutes of
    # the special meeting held on 8 September 2021, whose notice is dated
    # the 8th.
    "2021_9-September_Special-Council-Meeting_Minutes.pdf": "2021-09-08",
}


@register_scraper
class MorningtonShireScraper(BaseScraper):
    def __init__(self):
        super().__init__("mornington", "QLD", "https://www.mornington.qld.gov.au")

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        years_filter = getattr(self, "years_filter", None)

        # (name, date) -> kind -> [(label, url)], in page order.
        meetings: dict[tuple[str, str], dict[str, list[tuple[str, str]]]] = {}
        # Month-only labels, settled once every dated label has been read.
        undated: list[tuple[str, int, int, str, str, str]] = []

        for toggle in soup.select(".et_pb_toggle"):
            title = toggle.select_one(".et_pb_toggle_title")
            toggle_year = title.get_text(strip=True) if title else ""
            for link in toggle.select(".et_pb_toggle_content a[href]"):
                href = link["href"].strip()
                if not href.lower().endswith(".pdf"):
                    continue
                label = link.get_text(" ", strip=True)
                filename = href.rsplit("/", 1)[-1]
                if _EXTRA.search(label) or _EXTRA.search(filename):
                    continue
                if _MINUTES.search(label):
                    kind = "minutes"
                elif _AGENDA.search(label):
                    kind = "agenda"
                else:
                    continue
                name = (
                    "Special Council Meeting"
                    if re.search(r"special", label, re.IGNORECASE)
                    else "Ordinary Council Meeting"
                )

                year = self._year(label, toggle_year, filename)
                if year is None:
                    self.logger.warning(f"{self.council_name}: no year for {label!r}")
                    continue

                date = _MISDATED.get(filename) or self._date(label, year)
                if date is None:
                    month = _MONTH_ONLY.search(label)
                    if month:
                        number = parse_date(f"1 {month.group(1)} {year}").month
                        undated.append((name, year, number, kind, label, href))
                    else:
                        self.logger.warning(
                            f"{self.council_name}: no date in {label!r}"
                        )
                    continue
                papers = meetings.setdefault(
                    (name, date), {"agenda": [], "minutes": []}
                )
                papers[kind].append((label, href))

        self._place_month_only(meetings, undated)
        self._drop_borrowed_papers(meetings)

        results = []
        for (name, date), papers in meetings.items():
            if years_filter and int(date[:4]) not in years_filter:
                continue
            agenda_url = self._pick(papers["agenda"])
            minutes_url = self._pick(papers["minutes"])
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _year(label: str, toggle_year: str, filename: str) -> Optional[int]:
        for source in (label, toggle_year, filename):
            match = _YEAR.search(source)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _date(label: str, year: int) -> Optional[str]:
        match = _DAY_MONTH.search(label)
        if not match:
            return None
        try:
            return (
                parse_date(f"{match.group(1)} {match.group(2)} {year}")
                .date()
                .isoformat()
            )
        except (ValueError, OverflowError):
            return None

    def _place_month_only(self, meetings, undated) -> None:
        """Attach "Ordinary Council Meeting Agenda September 2023" to its meeting.

        Two 2023 agendas are labelled with the month alone. The day is not
        invented: the paper joins the meeting of the same kind already known
        from a dated label in that month, and only when there is exactly one.
        Both on the page today match one (20 September and 19 July 2023, the
        dates their minutes carry; the September agenda's own first page
        says 20 September).
        """
        for name, year, month, kind, label, href in undated:
            candidates = [
                key
                for key in meetings
                if key[0] == name and key[1].startswith(f"{year}-{month:02d}-")
            ]
            if len(candidates) != 1:
                self.logger.warning(
                    f"{self.council_name}: {label!r} gives only a month and "
                    f"matches {len(candidates)} meetings; leaving it out"
                )
                continue
            meetings[candidates[0]][kind].append((label, href))

    def _drop_borrowed_papers(self, meetings) -> None:
        """Keep a PDF linked from two meetings only on the one it is for.

        The "25 March 2026" agenda link is the 26 March 2025 agenda
        (2025_26-March_Ordinary-Council-meeting_Agenda.pdf), which the 2025
        list links too. Where the filename's own date settles it, the paper
        stays on that meeting and comes off the other.
        """
        owners: dict[str, list[tuple[tuple[str, str], str]]] = {}
        for key, papers in meetings.items():
            for kind, entries in papers.items():
                for _, href in entries:
                    owners.setdefault(href, []).append((key, kind))
        for href, holders in owners.items():
            if len({key for key, _ in holders}) < 2:
                continue
            file_date = self._filename_date(href)
            if file_date is None or not any(key[1] == file_date for key, _ in holders):
                continue
            for key, kind in holders:
                if key[1] != file_date:
                    self.logger.warning(
                        f"{self.council_name}: {key[1]} {kind} links {href}, "
                        f"the {file_date} paper; leaving it off"
                    )
                    meetings[key][kind] = [
                        e for e in meetings[key][kind] if e[1] != href
                    ]

    @staticmethod
    def _filename_date(href: str) -> Optional[str]:
        filename = href.rsplit("/", 1)[-1]
        year = _YEAR.search(filename)
        day_month = _DAY_MONTH.search(filename.replace("_", " "))
        if not year or not day_month:
            return None
        try:
            return (
                parse_date(f"{day_month.group(1)} {day_month.group(2)} {year.group(1)}")
                .date()
                .isoformat()
            )
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _pick(candidates: list[tuple[str, str]]) -> Optional[str]:
        # Some meetings list both unconfirmed and confirmed minutes; the
        # confirmed set is the record.
        if not candidates:
            return None
        confirmed = [url for label, url in candidates if not _UNCONFIRMED.search(label)]
        return confirmed[0] if confirmed else candidates[0][1]
