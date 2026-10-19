"""City of West Torrens—OpenCities listing, papers on a page per meeting.

The listing (``CWT CL Public Meetings``) is the OpenCities meetings module, but
its rows carry no ``data-cvid``: the accordion bodies are rendered inline and
hold only the meeting's details and a "View full details" link. The agenda and
minutes are on that page, so this runs with ``detail_pages``. The papers
themselves are produced by Objective Digital Meetings and served from
``/files/sharedassets/public/v/N/objective-digitalmeetings/YYYY/...``—the
``v/N`` segment is a version number, so the URLs cannot be built, only read.

A meeting page files each paper under an ``<h2>``—"Agenda", "Minutes"—with
the link labelled by the paper ("Council Agenda 15 September 2026"). A
cancelled meeting keeps its page and files a "Cancellation Notice" under both
headings (Special Council, 10 June 2025); a notice is neither paper, so such a
meeting has nothing to report and is skipped.

The listing honours ``(pagesize=N)``, so a year is one request—50 rows in
2024, the busiest year. It mixes Council, Special Council, the Council
Assessment Panel, General and Standing Committees and the Youth Advisory
Committee. Only Council and Special Council pages are fetched
(``meeting_types``): each page is a request of about 200 KB, and those are
the meetings that decide things. The Council Assessment Panel is a planning
body and would add 11 pages a year; it is left out to keep one production year
to about 18 requests, and is a one-line change to the pattern if wanted.

The listing starts in January 2023. Earlier meetings are on one static
archive page ("2022 - 2018"), a table of rows that each carry one paper:
date and time as ``dd/mm/yyyy hh:mm``, the meeting's name, its location, and a
link labelled "Agenda 29.86 MB" or "Minutes 213.89 KB". Rows for one meeting
are paired up by date, time and name. The archive is read only when a wanted
year predates the listing, so production's one-year run never fetches it.
Its Council section names meetings "Council and Standing Committees" (the
two met the same night on one agenda) and "Special Council Meeting".
"""

from __future__ import annotations

import datetime
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import (
    ScraperReturn,
    _merge_split_meetings,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _AGENDA,
    _MINUTES,
    _NOT_THE_PAPER,
    _ONE_ITEM,
    _is_pdf,
    _label,
    _papers,
    _pick,
)

_SITE = "https://www.westtorrens.sa.gov.au"
_ARCHIVE_URL = f"{_SITE}/Council/Meetings/Agendas-and-Minutes-archive"

# The live listing's first year. Its year filter offers 2016-2022 too, but
# those return no rows; those years are on the archive page.
_LISTING_FIRST_YEAR = 2023

_COUNCIL = re.compile(r"^(?:Special\s+)?Council$", re.IGNORECASE)

# A notice filed where a paper would be: "Cancellation Notice for Special
# Council Meeting 10 June 2025", or on the archive, a file named
# "agenda-council-and-standing-committee-notice-of-adjournment-21-june-2022".
# Matched on the label and the filename, since archive labels are only
# "Agenda 22.7 KB".
_NOTICE = re.compile(
    r"cancel|notice[\s-]+of[\s-]+(?:adjournment|postponement)|postpone",
    re.IGNORECASE,
)

# The archive's Council section. Its other sections are General Committees
# and the Council Assessment Panel, left out for the same reason as on the
# listing.
_ARCHIVE_SECTION = re.compile(r"^Council\s*&\s*Committee meetings$", re.IGNORECASE)
_ARCHIVE_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)")

# A confidential paper released after the meeting: "RELEASED Confidential
# Council Agenda 19 May 2026 - Item 20.2", or a whole confidential agenda
# ("RELEASED Agenda Confidential Council 21 January 2025"). Pages list them
# beside the meeting's own papers, sometimes first (Special Council, 27 June
# 2023).
_RELEASED = re.compile(r"\breleased\b", re.IGNORECASE)

_FIELD_TIME = re.compile(r"^\s*Meeting time:?\s*$", re.IGNORECASE)


def _is_notice(label: str, href: str) -> bool:
    return bool(_NOTICE.search(label) or _NOTICE.search(urlparse(href).path))


def _meeting_name(meeting_type: str) -> str:
    # The listing's type is "Council" or "Special Council"; the page itself
    # calls it a "Council meeting".
    return (
        meeting_type if meeting_type.endswith("Meeting") else f"{meeting_type} Meeting"
    )


def _absolute(href: str) -> str:
    # Some archive links are written without the leading slash
    # ("files/sharedassets/..."), which a browser would resolve under
    # /Council/Meetings/. The files live at the site root either way.
    href = href.strip()
    if not urlparse(href).scheme and not href.startswith("/"):
        href = "/" + href
    return urljoin(_SITE, href)


def papers_by_section(page: BeautifulSoup) -> dict[str, str]:
    """The agenda and minutes on a meeting page, by the ``<h2>`` each link
    follows.

    Only links that come after an "Agenda" or "Minutes" heading count, and
    only up to the next heading: the page's other sections are the location's
    map link, the audio recording and a "Related links" list.

    A section can hold more than the paper. Passed over: notices, attachment
    books, late items ("Council Agenda 19 August 2025 - Late Item 16.19") and
    one item's paper ("Council Agenda 15 October 2024 - Item 16.5 - ...",
    listed before the agenda itself). Ranked last: released confidential
    papers, so one stands in only when nothing else was published. Otherwise a
    label naming the paper ranks before one that does not.
    """
    body = page.find("div", class_="obj-meeting") or page
    agendas: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    section = None
    for element in body.find_all(["h2", "a"]):
        if element.name == "h2":
            heading = _label(element.get_text(" ", strip=True)).lower()
            section = heading if heading in ("agenda", "minutes") else None
            continue
        href = (element.get("href") or "").strip()
        if section is None or not href or not _is_pdf(href):
            continue
        label = _label(element.get_text(" ", strip=True))
        if (
            _NOT_THE_PAPER.search(label)
            or _ONE_ITEM.search(label)
            or _is_notice(label, href)
        ):
            continue
        word = _AGENDA if section == "agenda" else _MINUTES
        rank = 2 if _RELEASED.search(label) else 0 if word.search(label) else 1
        candidate = (label, _absolute(href), rank)
        (agendas if section == "agenda" else minutes).append(candidate)

    return _papers(_pick(agendas), _pick(minutes))


def _page_time(page: BeautifulSoup) -> str | None:
    """The start time from the details list: "07:00 PM - 10:30 PM"."""
    for label in page.find_all("span", class_="field-label"):
        if _FIELD_TIME.match(label.get_text(" ", strip=True)):
            value = label.find_next_sibling("span", class_="field-value")
            if value:
                match = re.search(
                    r"\d{1,2}:\d{2}\s*[AP]M",
                    value.get_text(" ", strip=True),
                    re.IGNORECASE,
                )
                if match:
                    return match.group()
    return None


def _page_location(page: BeautifulSoup) -> str | None:
    """The address under the page's "Location" heading, less its map link."""
    for h2 in page.find_all("h2"):
        if h2.get_text(strip=True).lower() != "location":
            continue
        paragraph = h2.find_next_sibling("p")
        if paragraph is None or not paragraph.find(
            "a", href=re.compile(r"google\.[^/]+/maps|maps\.google")
        ):
            return None
        for anchor in paragraph.find_all("a"):
            anchor.decompose()
        return re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True)).strip() or None
    return None


@register_scraper
class WestTorrensScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 32 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 32

    list_name = "CWT CL Public Meetings"
    page_size = 100
    detail_pages = True
    meeting_types = _COUNCIL

    def __init__(self):
        super().__init__(
            "west_torrens",
            "SA",
            f"{_SITE}/Council/Meetings/Agendas-and-minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        return papers_by_section(content)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        papers = self.papers(content)
        agenda_url = papers.get("agenda")
        minutes_url = papers.get("minutes")
        if not agenda_url and not minutes_url:
            # Usually a cancelled meeting, whose page holds only notices, or an
            # upcoming one whose agenda is not out yet. Say which files were
            # passed over, in case the rules wrongly reject a real paper.
            labels = [
                _label(a.get_text(" ", strip=True))
                for a in content.find_all("a", href=True)
                if _is_pdf(a["href"])
            ]
            if labels and not all(_NOTICE.search(label) for label in labels):
                self.logger.warning(
                    f"{row.date} {row.meeting_type}: no agenda or minutes among "
                    f"its {len(labels)} PDFs, so it is skipped: {labels[:6]}"
                )
            return None

        return ScraperReturn(
            name=_meeting_name(row.meeting_type),
            date=row.date,
            time=_page_time(content),
            webpage_url=row.detail_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=_page_location(content),
        )

    # ------------------------------------------------------------------
    # 2020-2022: the archive page
    # ------------------------------------------------------------------

    def _archive(self, wanted: set[int]) -> list[ScraperReturn]:
        # Not caught: the archive is the only source for these years, so a
        # failed fetch must fail the run, as a required listing page does,
        # rather than report it ok with no meetings.
        html = self.fetcher.fetch_with_requests(_ARCHIVE_URL)
        page = BeautifulSoup(html, "html.parser")
        body = page.find("div", id="main-content") or page

        meetings: dict[tuple, dict] = {}
        in_council = False
        for element in body.find_all(["h2", "div"]):
            if element.name == "h2":
                in_council = bool(
                    _ARCHIVE_SECTION.match(element.get_text(" ", strip=True))
                )
                continue
            if not in_council or "cwtRow" not in (element.get("class") or []):
                continue
            cells = element.find_all("div", recursive=False)
            if len(cells) < 4:
                continue
            when = _ARCHIVE_DATE.search(cells[0].get_text(" ", strip=True))
            if not when:
                continue
            day, month, year, time_str = when.groups()
            if int(year) not in wanted or int(year) < EARLIEST_YEAR:
                continue
            name = re.sub(r"\s+", " ", cells[1].get_text(" ", strip=True))
            location = re.sub(r"\s+", " ", cells[2].get_text(" ", strip=True)) or None
            meeting = meetings.setdefault(
                (year, month, day, time_str, name),
                {"location": location, "agenda": None, "minutes": None},
            )
            for anchor in cells[3].find_all("a", href=True):
                href = anchor["href"]
                label = _label(anchor.get_text(" ", strip=True))
                if not _is_pdf(href) or _is_notice(label, href):
                    continue
                if _NOT_THE_PAPER.search(urlparse(href).path.replace("-", " ")):
                    continue
                # The label is only the paper's kind and size.
                if _AGENDA.match(label) and not meeting["agenda"]:
                    meeting["agenda"] = _absolute(href)
                elif _MINUTES.match(label) and not meeting["minutes"]:
                    meeting["minutes"] = _absolute(href)

        results = []
        for (year, month, day, time_str, name), meeting in meetings.items():
            agenda_url, minutes_url = meeting["agenda"], meeting["minutes"]
            if not agenda_url and not minutes_url:
                continue
            date = datetime.date(int(year), int(month), int(day))
            results.append(
                ScraperReturn(
                    name=_meeting_name(name),
                    # Written out, because dateutil reads "01/02/2022" as 2
                    # January.
                    date=f"{date.day} {date:%B %Y}",
                    time=time_str,
                    webpage_url=_ARCHIVE_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=meeting["location"],
                )
            )
        if not results:
            self.logger.warning(
                f"No Council meetings for {sorted(wanted)} on {_ARCHIVE_URL}"
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results: list[ScraperReturn] = []
        if max(wanted) >= _LISTING_FIRST_YEAR:
            results += super().scraper()
        archived = {y for y in wanted if y < _LISTING_FIRST_YEAR}
        if archived:
            results += self._archive(archived)
        results = _merge_split_meetings(results)
        if not results:
            self.logger.warning(f"No meetings found for {self.council_name}")
        return results
