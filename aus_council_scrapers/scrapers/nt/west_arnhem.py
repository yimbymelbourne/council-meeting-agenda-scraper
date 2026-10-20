import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://westarnhem.nt.gov.au"
_LISTING_URL = f"{_BASE_URL}/corporate-documents/minutes-and-agendas"

# One Drupal page holds every paper since 2022: an accordion per body
# ("Ordinary Council Meetings", "Special Council Meetings", the four Local
# Authorities and the committees), with a panel per year of links labelled
# "2026.09.22 Ordinary Council Meeting Agenda". Only the two council
# sections are read; the Local Authorities and committees advise council
# rather than decide, and Special meetings before 2025 sit in the Ordinary
# section anyway, so each paper's type comes from its own label.
_SECTIONS = ("ordinary council meetings", "special council meetings")
_LABEL_DATE = re.compile(r"^(20\d\d)[.\-](\d\d)[.\-](\d\d)\b")
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
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
        ]
    )
}
_FILE_ISO_DATE = re.compile(r"(?<!\d)(20\d\d)[._\-](\d\d)[._\-](\d\d)(?!\d)")
_FILE_DMY_DATE = re.compile(r"(?<!\d)(\d\d)[._](\d\d)[._](20\d\d)(?!\d)")
_FILE_LONG_DATE = re.compile(
    r"(?<!\d)(\d{1,2})[\s_\-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_\-]+(20\d\d)",
    re.IGNORECASE,
)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
# Second documents for a meeting that already has its agenda ("Agenda -
# Late Report", "Supplementary Agenda", "Item 9.5 ... ATTACHMENT") and
# notices that are not papers at all.
_NOT_A_PAPER = re.compile(
    r"supplementary|late|attachment|addendum|postpone|notice", re.IGNORECASE
)
# "2023.11.13 Ordinary Council Meeting Agenda - (CANCELLED)": the meeting
# never sat, so its agenda describes no meeting.
_CANCELLED = re.compile(r"cancel", re.IGNORECASE)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
# How far apart an agenda and minutes can be dated and still be one meeting;
# see _pair_postponed.
_POSTPONED_DAYS = 2
# Two special meetings sat on 17 June 2026, at 9:00 and 9:30 am, each with
# its own agenda and minutes; the times are from page 1 of each paper, read
# on 20 Oct 2026. The listing does not give times, so a day with several
# sittings that is not in this table is emitted with no time and a warning.
_SITTING_TIMES = {
    f"{_BASE_URL}/sites/default/files/2026-06/2026-06-17%20Special%20Council%20Meeting%20-%20Agenda.pdf": "09:00",
    f"{_BASE_URL}/sites/default/files/2026-07/2026-06-17%20Special%20Council%20Meeting%20-%20Minutes%20Confirmed.pdf": "09:00",
    f"{_BASE_URL}/sites/default/files/2026-06/2026-06-17%20Special%20Council%20Meeting%20Agenda_1.pdf": "09:30",
    f"{_BASE_URL}/sites/default/files/2026-07/2026-06-17%20Special%20Council%20Meeting%20Minutes%20Confirmed.pdf": "09:30",
}


def _file_date(filename: str) -> Optional[datetime.date]:
    for pattern, order in (
        (_FILE_ISO_DATE, "ymd"),
        (_FILE_DMY_DATE, "dmy"),
        (_FILE_LONG_DATE, "dMy"),
    ):
        match = pattern.search(filename)
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if order == "ymd":
                return datetime.date(int(a), int(b), int(c))
            if order == "dmy":
                return datetime.date(int(c), int(b), int(a))
            return datetime.date(int(c), _MONTHS[b[:3].lower()], int(a))
        except ValueError:
            continue
    return None


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    special: bool
    date: datetime.date
    url: str
    file_date: Optional[datetime.date]


@register_scraper
class WestArnhemScraper(BaseScraper):
    def __init__(self):
        super().__init__("west_arnhem", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, soup: BeautifulSoup) -> list[_Paper]:
        papers = []
        for title in soup.select("div.field--name-field-title"):
            if title.get_text(" ", strip=True).lower() not in _SECTIONS:
                continue
            # The section's accordion is the next block after its title.
            body = title.find_next(
                "div", class_="field--name-field-accordion-item-blank-field"
            )
            if body is None:
                continue
            for anchor in body.select(".accordion-body a[href]"):
                label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
                match = _LABEL_DATE.match(label)
                if not match:
                    # An unlabelled link is an older upload left beside its
                    # replacement; "Financial Report - June 2023" is a report.
                    continue
                if _CANCELLED.search(label) or _NOT_A_PAPER.search(label):
                    continue
                if _MINUTES.search(label):
                    kind = "minutes"
                elif _AGENDA.search(label):
                    kind = "agenda"
                else:
                    continue
                url = requote_uri(urljoin(_LISTING_URL, anchor["href"].strip()))
                try:
                    date = datetime.date(*(int(g) for g in match.groups()))
                except ValueError:
                    self.logger.warning(
                        f"{self.council_name}: bad date in {label!r}; skipped"
                    )
                    continue
                papers.append(
                    _Paper(
                        kind=kind,
                        special=bool(_SPECIAL.search(label)),
                        date=date,
                        url=url,
                        file_date=_file_date(unquote(url.rsplit("/", 1)[-1])),
                    )
                )
        return papers

    @staticmethod
    def _drop_misfiled(papers: list[_Paper]) -> list[_Paper]:
        """Drop a link whose file is also linked under another meeting's label.

        "2023.06.23 Ordinary Council Meeting Agenda" links
        2023.07.12_special_council_meeting_agenda.pdf, the same URL that
        "2023.07.12 Special Council Meeting Agenda" links, so it is the July
        paper and 23 June has no agenda online. Only a shared URL counts. A
        date in the file name does not: "2025.01.29 Ordinary Council Meeting
        Minutes" links a file named 2025.02.18 Ordinary Council Meeting
        Minutes.pdf whose first page is the 29 January 2025 minutes (the real
        February minutes are another file), and "2024.11.19 ... Minutes"
        links one named for 18 December 2024 that is the 19 November minutes.
        The council names files carelessly and labels them carefully. The
        file-name date only decides which of the labels sharing a URL owns
        it; if no file date settles that, every label keeps the link.
        """
        labels: dict[tuple[str, str], set[tuple[datetime.date, bool]]] = {}
        for p in papers:
            labels.setdefault((p.kind, p.url), set()).add((p.date, p.special))
        return [
            p
            for p in papers
            if not (
                len(labels[(p.kind, p.url)]) > 1
                and p.file_date
                and p.file_date != p.date
            )
        ]

    @staticmethod
    def _pair_postponed(meetings: dict[tuple[datetime.date, bool], list[dict]]) -> None:
        """Join an agenda and minutes dated a day or two apart.

        The 21 October 2024 ordinary meeting was postponed to the 23rd: the
        agenda is labelled 21 October and the minutes 23 October. An
        agenda-only meeting is joined to a minutes-only one of the same type
        only when each is the other's sole candidate, and the minutes' date
        is kept, because the minutes record when the meeting sat. Days with
        more than one sitting are left alone.
        """

        def lone(kind: str) -> list[tuple[datetime.date, bool]]:
            return [
                key
                for key, sittings in meetings.items()
                if len(sittings) == 1
                and {k for k in ("agenda", "minutes") if sittings[0].get(k)} == {kind}
            ]

        for agenda_key in lone("agenda"):
            date, special = agenda_key
            near = [
                key
                for key in lone("minutes")
                if key[1] == special and abs((key[0] - date).days) <= _POSTPONED_DAYS
            ]
            if len(near) != 1:
                continue
            rivals = [
                key
                for key in lone("agenda")
                if key[1] == special
                and abs((key[0] - near[0][0]).days) <= _POSTPONED_DAYS
            ]
            if rivals == [agenda_key]:
                agenda = meetings.pop(agenda_key)[0]["agenda"]
                meetings[near[0]][0]["agenda"] = agenda

    def _sittings(
        self, date: datetime.date, special: bool, found: dict[str, list[str]]
    ) -> list[dict]:
        """One entry per sitting on a day: its agenda, minutes and time.

        A day normally has one agenda and one set of minutes. When it has
        several distinct ones, the council sat more than once that day, as on
        17 June 2026. Papers whose sitting time is known (_SITTING_TIMES) are
        grouped by it; otherwise the n-th agenda listed goes with the n-th
        minutes, with a warning so the pairing gets checked.
        """
        agendas = found.get("agenda", [])
        minutes = found.get("minutes", [])
        if len(agendas) <= 1 and len(minutes) <= 1:
            return [
                {
                    "agenda": agendas[0] if agendas else None,
                    "minutes": minutes[0] if minutes else None,
                    "time": None,
                }
            ]
        if all(url in _SITTING_TIMES for url in agendas + minutes):
            by_time: dict[str, dict] = {}
            for kind, urls in (("agenda", agendas), ("minutes", minutes)):
                for url in urls:
                    sitting = by_time.setdefault(
                        _SITTING_TIMES[url],
                        {"agenda": None, "minutes": None, "time": _SITTING_TIMES[url]},
                    )
                    sitting[kind] = sitting[kind] or url
            return [by_time[time] for time in sorted(by_time)]
        self.logger.warning(
            f"{self.council_name}: {max(len(agendas), len(minutes))} sittings on "
            f"{date} with no known times; agendas and minutes paired in listing "
            f"order: {agendas} / {minutes}"
        )
        return [
            {
                "agenda": agendas[i] if i < len(agendas) else None,
                "minutes": minutes[i] if i < len(minutes) else None,
                "time": None,
            }
            for i in range(max(len(agendas), len(minutes)))
        ]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the scraper's only request, and an
        # empty list would report a broken site as a council with no
        # meetings.
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        papers = self._drop_misfiled(self._papers(soup))

        found: dict[tuple[datetime.date, bool], dict[str, list[str]]] = {}
        for paper in papers:
            if paper.date.year not in wanted:
                continue
            urls = found.setdefault((paper.date, paper.special), {}).setdefault(
                paper.kind, []
            )
            if paper.url not in urls:
                urls.append(paper.url)
        meetings = {
            key: self._sittings(*key, papers_by_kind)
            for key, papers_by_kind in found.items()
        }
        self._pair_postponed(meetings)

        results = []
        for (date, special), sittings in sorted(meetings.items()):
            for sitting in sittings:
                agenda_url = sitting["agenda"]
                minutes_url = sitting["minutes"]
                results.append(
                    ScraperReturn(
                        name=(
                            "Special Council Meeting"
                            if special
                            else "Ordinary Council Meeting"
                        ),
                        date=date.isoformat(),
                        time=sitting["time"],
                        webpage_url=_LISTING_URL,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
