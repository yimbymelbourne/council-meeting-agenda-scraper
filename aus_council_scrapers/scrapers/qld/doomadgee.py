import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.doomadgee.qld.gov.au"
# WordPress with the WP Download Manager plugin. Agendas and minutes are on
# two pages as "packages": a title, and a Download button whose URL is in a
# data attribute. A package can hold several files (a zip on download), and
# its title is not to be trusted: "Council Agenda May 14 2026" is the May
# minutes, and the April 2026 agenda and minutes packages both hold the
# April financials. So every package wanted is opened on its own page,
# `/download/<slug>/`, which names each file, and each file is classified
# by its own name. The listing cannot stand in for that page: the May 2026
# package is a single PDF, titled and listed as an agenda, and only the
# file name ("May-Ordinary-Council-Meeting-MInutes.pdf") says it is the
# minutes.
_AGENDAS_URL = f"{_BASE_URL}/our-council/council-agendas/"
_MINUTES_URL = f"{_BASE_URL}/our-council/council-minutes/"

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_SEP = r"[\s_\-,.]+"
# "14th November 2025", "May 14 2026", "October-15-2020", "16th & 17th
# November 2021" (the first day).
_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?(?:" + _SEP + r"(?:&|and)" + _SEP + r"\d{1,2}(?:st|nd|rd|th)?)?"
    + _SEP + _MONTH + _SEP + r"(20\d\d)",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    r"\b" + _MONTH + _SEP + r"(\d{1,2})(?:st|nd|rd|th)?(?:" + _SEP + r"(?:&|and)" + _SEP
    + r"\d{1,2}(?:st|nd|rd|th)?)?(?:" + _SEP + r"continued)?" + _SEP + r"(20\d\d)",
    re.IGNORECASE,
)
# A day and month with no year ("Special Meeting – Unconfirmed Minutes
# April 7"), which takes the package's year.
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?" + _SEP + _MONTH + r"\b", re.IGNORECASE)
_MONTH_DAY = re.compile(r"\b" + _MONTH + _SEP + r"(\d{1,2})(?:st|nd|rd|th)?\b(?!" + _SEP + r"\d)", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d\d)\b")
_MONTH_ONLY = re.compile(r"\b" + _MONTH + r"\b", re.IGNORECASE)

# Packages that are notices, not papers: cancellations, changes of date,
# "on hold".
_NOTICE = re.compile(r"cancel|notice|change|on hold", re.IGNORECASE)
# "Council-Minites-21st-September-2023.pdf" is a typo the council made.
_MINUTES = re.compile(r"minut|minuet|minit", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_ATTACHMENT = re.compile(r"attach|attchment", re.IGNORECASE)
_FINANCIALS = re.compile(r"financ", re.IGNORECASE)
_UPLOAD_STAMP = re.compile(r"^\d+wpdm_")
_MEETING_FOR = re.compile(r"\bfor\s+" + _MONTH + r"\s+council\s+meeting", re.IGNORECASE)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)


def _full_date(text: str) -> Optional[datetime.date]:
    for pattern, day_group, month_group in ((_DAY_MONTH_YEAR, 1, 2), (_MONTH_DAY_YEAR, 2, 1)):
        for match in pattern.finditer(text):
            try:
                return datetime.date(
                    int(match.group(3)),
                    _MONTHS[match.group(month_group)[:3].lower()],
                    int(match.group(day_group)),
                )
            except ValueError:
                continue
    return None


def _day_month(text: str) -> Optional[tuple[int, int]]:
    for pattern, day_group, month_group in ((_DAY_MONTH, 1, 2), (_MONTH_DAY, 2, 1)):
        match = pattern.search(text)
        if match:
            return int(match.group(day_group)), _MONTHS[match.group(month_group)[:3].lower()]
    return None


@dataclass
class _Package:
    page_kind: str  # the listing it is on: "agenda" or "minutes"
    title: str
    url: str  # the package page, /download/<slug>/
    package_id: str
    year: Optional[int]


@dataclass
class _Paper:
    kind: str
    url: str
    special: bool
    date: Optional[datetime.date]
    confirmed: bool
    # (year, month) for a paper dated only to the month.
    month: Optional[tuple[int, int]] = None
    # (year, month) of the meeting, where the title says which month's
    # meeting a paper dated in another month is for.
    group: Optional[tuple[int, int]] = None


@register_scraper
class DoomadgeeScraper(BaseScraper):
    # Two listings plus one package page per paper, all on one
    # Cloudflare-fronted host that takes 2-6 s to answer our identifying
    # User-Agent (0.1-0.3 s for a browser-shaped one; we do not switch,
    # because AGENTS.md keeps overrides for councils that refuse us). So
    # the cost grows with the year: 30 s for 2026 in October (12 requests),
    # 106 s for all of 2025 (about 38, the 2026 packages included, since a
    # December paper can be filed with the next year's). Set from the full
    # year so dispatch starts it early.
    expected_seconds = 100.0

    def __init__(self):
        super().__init__("doomadgee", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _packages(html: str, page_kind: str) -> list[_Package]:
        soup = BeautifulSoup(html, "html.parser")
        packages = []
        year: Optional[int] = None
        for button in soup.select("[data-downloadurl]"):
            download = button["data-downloadurl"]
            query = parse_qs(urlparse(download).query)
            package_id = (query.get("wpdmdl") or [None])[0]
            if not package_id:
                continue
            card = button.find_parent(class_=re.compile(r"link-template-default|wpdm-link-tpl"))
            if card is None:
                continue
            title_el = card.select_one(".package-title, .ptitle")
            if title_el is None:
                continue
            for label in title_el.select(".label"):
                label.extract()
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))
            # The agendas page files packages under "2026 Council Agendas";
            # the minutes page has no headings, so a title without a year
            # ("Special Meeting – Unconfirmed Minutes April 7") takes the
            # year of the package listed before it, the page being newest
            # first.
            heading = card.find_previous("h5")
            heading_year = _YEAR.search(heading.get_text()) if heading and page_kind == "agenda" else None
            slug = urlparse(download).path
            title_year = _YEAR.search(title) or _YEAR.search(slug)
            if heading_year:
                year = int(heading_year.group(1))
            elif title_year:
                year = int(title_year.group(1))
            packages.append(
                _Package(
                    page_kind=page_kind,
                    title=title,
                    url=urljoin(_BASE_URL, slug),
                    package_id=package_id,
                    year=year,
                )
            )
        return packages

    def _files(self, package: _Package) -> list[tuple[str, str]]:
        """(download URL, file name) for each file in a package."""
        # Left to raise: a package page that cannot be read would drop that
        # meeting's paper without a word.
        html = self.fetcher.fetch_with_requests(package.url)
        soup = BeautifulSoup(html, "html.parser")
        files: dict[str, str] = {}
        missing: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            query = parse_qs(urlparse(anchor["href"]).query)
            if (query.get("wpdmdl") or [None])[0] != package.package_id:
                continue
            index = (query.get("ind") or [None])[0]
            name = unquote((query.get("filename") or [""])[0])
            if index and (name or index not in files):
                files[index] = name
            # WPDM lists a file whose upload is gone as "NAN B", and its
            # link answers 200 with an empty body (`application/x-empty`):
            # "Ordinary-Meeting-June-16-2022.pdf", the June, July and
            # August 2022 agendas. Real files can read "0 KB" here, so
            # only this marker counts.
            item = anchor.find_parent(class_="wpdm-filelist-item")
            size = item.select_one(".wpdm-filelist-item__size") if item else None
            if index and size and size.get_text(strip=True).upper() == "NAN B":
                missing.add(index)
        for index in missing:
            self.logger.warning(
                f"{self.council_name}: {files[index] or index!r} in {package.title!r} "
                f"is an empty upload; skipped"
            )
        # The refresh token on the page's own links expires; the package id
        # and file index alone are a stable link that answers with the file.
        return [
            (f"{package.url}?wpdmdl={package.package_id}&ind={index}", name)
            for index, name in files.items()
            if index not in missing
        ]

    def _papers(self, package: _Package) -> list[_Paper]:
        files = self._files(package)
        # The same file uploaded twice, once under WPDM's upload stamp
        # ("1697514724wpdm_20231013161104211.pdf" beside
        # "20231013161104211.pdf"), is one paper.
        candidates: dict[str, tuple[str, str]] = {}
        for url, name in files:
            stripped = _UPLOAD_STAMP.sub("", name)
            candidates.setdefault(stripped.lower() or url, (url, stripped))

        typed: list[tuple[str, str, str]] = []
        untyped: list[tuple[str, str]] = []
        for url, name in candidates.values():
            text = name.replace("-", " ").replace("_", " ")
            if name and not name.lower().endswith(".pdf"):
                # "Notice.png", an attachments zip.
                continue
            if _ATTACHMENT.search(text):
                # Attachment packs are never the paper, whatever the rest of
                # the package is called. Their names say "agenda" or
                # "minutes" too ("ATTACHMENTS-TO-COUNCIL-AGENDA-June-2022.pdf",
                # "Attachment-for-Minutes-Special-Meeting-29-July-2022.pdf"),
                # so this comes before the type check.
                continue
            if _FINANCIALS.search(text):
                # "Financials-April-002.pdf", filed beside both April 2026
                # papers.
                continue
            if _MINUTES.search(text):
                typed.append(("minutes", url, text))
            elif _AGENDA.search(text):
                typed.append(("agenda", url, text))
            else:
                untyped.append((url, text))

        if untyped and not typed and len(untyped) == 1:
            # A lone paper whose name says only what meeting it is
            # ("Jan-2025-Combined.pdf", "Ordinary-Meeting-June-16-2022.pdf",
            # "Confirmed-Special-Council-Meeting-29th-August-2025.pdf", or a
            # scan named by its timestamp) is what the package title says
            # it is, or failing that what the listing it is on holds.
            url, text = untyped.pop()
            title_minutes = bool(_MINUTES.search(package.title))
            title_agenda = bool(_AGENDA.search(package.title))
            if title_minutes != title_agenda:
                kind = "minutes" if title_minutes else "agenda"
            else:
                kind = package.page_kind
            typed.append((kind, url, text))
        for url, text in untyped:
            self.logger.warning(
                f"{self.council_name}: cannot tell what {text!r} in {package.title!r} "
                f"is beside its other files; skipped {url}"
            )
        if not files:
            self.logger.warning(f"{self.council_name}: {package.title!r} ({package.url}) has no files")

        # "May – Confirmed Council Minutes 4th June 2024 – For May Council
        # Meeting": the May meeting, moved into June. Its agenda is filed
        # under 31 May, so it pairs within May.
        meeting_for = _MEETING_FOR.search(package.title)

        papers = []
        for kind, url, text in typed:
            # The file's own name dates it where it can ("Minutes-of-Ordinay-
            # Meeting-October-15-2020.pdf" in "Confirmed Minutes – October
            # 2020"), then the package title, then its slug.
            date = (
                _full_date(text)
                or _full_date(package.title)
                # The slug keeps the title the package was first given:
                # "January – Confirmed Minutes 2026" is
                # `january-confirmed-council-minutes-january-21st-2026`.
                or _full_date(package.url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
            )
            if date is None and package.year:
                day_month = _day_month(package.title) or _day_month(text)
                if day_month:
                    try:
                        date = datetime.date(package.year, day_month[1], day_month[0])
                    except ValueError:
                        date = None
            month: Optional[tuple[int, int]] = None
            if date is None:
                # Month-only ("March – Confirmed Minutes 2026"): kept for
                # now, to take the day of the month's other paper.
                month_match = _MONTH_ONLY.search(package.title) or _MONTH_ONLY.search(text)
                if month_match and package.year:
                    month = (package.year, _MONTHS[month_match.group(1)[:3].lower()])
                else:
                    self.logger.warning(
                        f"{self.council_name}: cannot date {package.title!r} ({text or url}); skipped"
                    )
                    continue
            group = None
            if meeting_for and package.year:
                group = (package.year, _MONTHS[meeting_for.group(1)[:3].lower()])
            papers.append(
                _Paper(
                    kind=kind,
                    url=url,
                    special=bool(_SPECIAL.search(f"{package.title} {text}")),
                    date=date,
                    confirmed=not _UNCONFIRMED.search(f"{package.title} {text}"),
                    month=month,
                    group=group,
                )
            )
        return papers

    def _date_month_only(self, papers: list[_Paper]) -> list[_Paper]:
        """Give a month-only paper the day of the one meeting of its type
        that month, or leave it out. Never a guessed day."""
        dated = [p for p in papers if p.date]
        for paper in papers:
            if paper.date:
                continue
            days = {
                p.date
                for p in dated
                if p.kind != paper.kind
                and p.special == paper.special
                and (p.date.year, p.date.month) == paper.month
            }
            if len(days) == 1:
                paper.date = days.pop()
                dated.append(paper)
            else:
                self.logger.warning(
                    f"{self.council_name}: {paper.url} gives only {paper.month} and no "
                    f"single meeting that month to date it; left out"
                )
        return dated

    @staticmethod
    def _meetings(papers: list[_Paper]) -> list[tuple[datetime.date, bool, Optional[str], Optional[str]]]:
        """Pair agendas and minutes, as (date, special, agenda, minutes).

        Meetings here move often, and the agenda keeps its first date: the
        package filed as 30 November 2023 was changed to the 28th, the date
        its minutes give. So within a month, the one agenda and the one set
        of minutes of a meeting type pair whatever their days, and the
        minutes' date stands. Otherwise they pair on the exact day.
        Confirmed minutes win over unconfirmed ones for the same day.
        """
        groups: dict[tuple[int, int, bool], dict[str, dict[datetime.date, _Paper]]] = {}
        for paper in papers:
            year, month = paper.group or (paper.date.year, paper.date.month)
            by_kind = groups.setdefault((year, month, paper.special), {})
            docs = by_kind.setdefault(paper.kind, {})
            current = docs.get(paper.date)
            if current is None or (paper.confirmed and not current.confirmed):
                docs[paper.date] = paper

        meetings = []
        for (_, _, special), by_kind in groups.items():
            agendas = by_kind.get("agenda", {})
            minutes = by_kind.get("minutes", {})
            if len(agendas) == 1 and len(minutes) == 1:
                (agenda,) = agendas.values()
                (minute,) = minutes.values()
                meetings.append((minute.date, special, agenda.url, minute.url))
                continue
            for date in sorted(set(agendas) | set(minutes)):
                agenda, minute = agendas.get(date), minutes.get(date)
                meetings.append(
                    (date, special, agenda.url if agenda else None, minute.url if minute else None)
                )
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Both left to raise: either page failing would drop half of every
        # meeting's papers.
        packages = self._packages(
            self.fetcher.fetch_with_requests(_AGENDAS_URL), "agenda"
        ) + self._packages(self.fetcher.fetch_with_requests(_MINUTES_URL), "minutes")

        seen: set[str] = set()
        papers: list[_Paper] = []
        for package in packages:
            # The November 2025 minutes are listed on both pages.
            if package.package_id in seen or _NOTICE.search(package.title):
                continue
            seen.add(package.package_id)
            # A December meeting's papers can be filed with the next year's.
            if package.year is None or not ({package.year, package.year - 1} & wanted):
                continue
            papers.extend(self._papers(package))
        papers = [p for p in self._date_month_only(papers) if p.date.year in wanted]

        results = []
        for date, special, agenda_url, minutes_url in sorted(
            self._meetings(papers), key=lambda m: (m[0], m[1])
        ):
            results.append(
                ScraperReturn(
                    name="Special Meeting" if special else "Ordinary Council Meeting",
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_AGENDAS_URL if agenda_url else _MINUTES_URL,
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
