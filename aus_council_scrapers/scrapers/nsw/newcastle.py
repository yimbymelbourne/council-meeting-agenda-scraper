import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper

# The council website's pages for the meetings before the move to Resolve.
# Each is paged, ten meetings to a page, newest first (`?page=2`, ...), with
# one expandable panel per meeting holding a table of its papers. The bare
# host is used because www. 301s to it. robots.txt allows both paths and
# sets no Crawl-delay.
_PREVIOUS = (
    "https://newcastle.nsw.gov.au/council/council-meetings/previous-council-terms"
)
COUNCIL_ARCHIVE = f"{_PREVIOUS}/previous-ordinary-extraordinary-council-meetings"
COMMITTEE_ARCHIVE = f"{_PREVIOUS}/previous-committee-meetings"

# The council listing reached its last page at 4 and the committee listing
# at 3 in October 2026, and nothing will be added to either. This only
# guards against a pager that never runs out.
_MAX_PAGES = 10


@register_scraper
class NewcastleScraper(ResolveScraper):
    # Newcastle moved to Resolve for the council term that started on 8
    # October 2024; that inaugural meeting is the tenant's first event.
    # Meetings from January 2022 to August 2024 are on the council website's
    # previous-council-terms pages, read by `other_meetings`. Papers from
    # before 2022 are by request only ("archived minutes pre 2022, please
    # complete this form"). Production asks for a year that is all Resolve,
    # so the website costs it nothing.
    tenant = "newcastle"
    resolve_from = datetime.date(2024, 10, 8)

    # Council (extraordinary and adjourned meetings are filed under the
    # Ordinary Council type too, and told apart by the event name) and the
    # Development Application Committee, which determines DAs. Left out are
    # the Public Briefing and Public Voice sessions, where councillors are
    # briefed or residents address them and nothing is decided, and the
    # seven standing and strategic advisory committees. The tenant lists
    # about 50 events a year, and each kept one costs a detail request.
    meeting_types = re.compile(
        r"^(Ordinary Council|Development Application Committee)$"
    )

    def __init__(self):
        super().__init__("newcastle", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = self.before_resolve(wanted)
        if not years:
            return []
        results = self._archive(COUNCIL_ARCHIVE, _council_record, years)
        results += self._archive(COMMITTEE_ARCHIVE, _committee_record, years)
        return sorted(results, key=lambda r: r.date)

    def _archive(
        self, listing: str, record_for, years: list[int]
    ) -> list[ScraperReturn]:
        results = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"{listing}?page={page}" if page > 1 else listing
            panels = _panels(self.fetcher.fetch_with_requests(url))
            if not panels:
                if page == 1:
                    # The first page always has meetings; none means the
                    # layout changed, which must not pass for an empty year.
                    raise RuntimeError(
                        f"{self.council_name}: no meetings found on {url}"
                    )
                break
            for date, time, location, papers in panels:
                if date.year not in years or date >= self.resolve_from:
                    continue
                record = record_for(papers)
                if not record:
                    # A committee night with no Development Applications
                    # Committee (Public Voice or a briefing only), or a
                    # meeting with no PDF papers.
                    continue
                name, agenda_url, minutes_url = record
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=time,
                        webpage_url=url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                        location=location,
                    )
                )
            # Newest first, so a page that ends before the oldest wanted
            # year is the last one needed.
            if panels[-1][0].year < min(years):
                break
        return results


# "06:00 pm Tuesday, 27 Aug 2024", then the venue after a <br>. Months are
# abbreviated, sometimes as "Sept", or written out ("July", "June").
_WHEN = re.compile(
    r"(?P<time>\d{1,2}:\d{2}\s*[ap]m)\s+\w+day,?\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)


def _panels(
    html: str,
) -> list[tuple[datetime.date, Optional[str], Optional[str], list]]:
    """Each meeting panel's date, time, venue and papers. The papers are
    (section, label, url) for every PDF in the panel's table, the section
    being the table's heading row above it ("Agenda", "Minutes")."""
    soup = BeautifulSoup(html, "html.parser")
    panels = []
    for item in soup.select("div.council-meeting__item"):
        header = item.select_one(".council-meeting__header__title p")
        if not header:
            continue
        lines = list(header.stripped_strings)
        match = _WHEN.search(lines[0] if lines else "")
        if not match:
            continue
        date = parse_date(match.group("date"), dayfirst=True).date()
        hour_minute, half = match.group("time")[:-2].strip(), match.group("time")[-2:]
        hour, minute = hour_minute.split(":")
        time = f"{int(hour)}:{minute} {half.upper()}"
        location = lines[1] if len(lines) > 1 else None

        papers = []
        section = None
        for row in item.select("table tr"):
            heading = row.find("td", class_="heading")
            if heading:
                section = heading.get_text(" ", strip=True)
                continue
            link = row.find("a", href=True)
            if not link or not link.get_text(strip=True):
                continue
            # PDFs only: two meetings' minutes are a .docx (Council, 26
            # April 2022; the committee, 18 October 2022), and the webcast
            # rows link YouTube. Those meetings keep their agendas.
            if not urlparse(link["href"]).path.lower().endswith(".pdf"):
                continue
            papers.append(
                (
                    section,
                    link.get_text(" ", strip=True),
                    urljoin(COUNCIL_ARCHIVE, link["href"]),
                )
            )
        panels.append((date, time, location, papers))
    return panels


# Every panel on the council listing heads its papers "Council Meeting",
# so the meeting type comes from the paper's own label: "Ordinary Council
# Meeting Agenda", "Extraordinary Council Meeting Agenda", "Ordinary
# Council Meeting 27 June 2023". The other agenda rows are attachments
# distributed under separate cover, lord mayoral minutes, late items and
# supplementary reports, filed as PDFs of their own.
_COUNCIL_AGENDA = re.compile(
    r"^(?P<kind>Ordinary|Extraordinary) Council Meeting\b", re.I
)
_COUNCIL_MINUTES = re.compile(
    r"\bminutes\b.*\bcouncil meeting\b|\bcouncil meeting\b.*\bminutes\b", re.I
)
_NOT_THE_AGENDA = re.compile(r"attachment|late item|supplementary", re.I)


def _council_record(papers) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    agenda = _first(
        papers,
        "Agenda",
        lambda label: _COUNCIL_AGENDA.match(label)
        and not _NOT_THE_AGENDA.search(label),
    )
    minutes = _first(papers, "Minutes", _COUNCIL_MINUTES.search)
    if not (agenda or minutes):
        return None
    labels = " ".join(label for label, _ in filter(None, (agenda, minutes)))
    # Named as Resolve names the same meetings.
    name = (
        "Extraordinary Council"
        if re.search(r"extraordinary", labels, re.I)
        else "Ordinary Council"
    )
    return name, agenda and agenda[1], minutes and minutes[1]


# A committee panel is one evening's committees together—Public Voice,
# Briefing and the Development Applications Committee—each with its own
# agenda and minutes, plus the DA reports' attachments. Only the DAC is
# kept, which determines DAs. Its labels vary ("Development Applications
# Committee Meeting Agenda", "Minutes of Extraordinary Deveopment
# Applications Committee"), and its attachments are filed in the same
# section ("Development Applications Committee - Attachments distributed
# under separate cover").
_DAC = r"\bDev\w*\s+Applications?\s+Committee\b"
_DAC_AGENDA = re.compile(rf"^(Extraordinary\s+)?{_DAC}(\s+Meeting)?\s+Agenda\b", re.I)
_DAC_MINUTES = re.compile(rf"\bminutes\b.*{_DAC}|{_DAC}.*\bminutes\b", re.I)


def _committee_record(papers) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    agenda = _first(papers, "Agenda", _DAC_AGENDA.match)
    minutes = _first(papers, "Minutes", _DAC_MINUTES.search)
    if not (agenda or minutes):
        return None
    labels = " ".join(label for label, _ in filter(None, (agenda, minutes)))
    # The 25 July 2023 meeting's agenda is labelled plainly and its minutes
    # as the extraordinary meeting's, so either label decides.
    name = "Development Application Committee"
    if re.search(r"extraordinary", labels, re.I):
        name = f"Extraordinary {name}"
    return name, agenda and agenda[1], minutes and minutes[1]


def _first(papers, section: str, matches) -> Optional[tuple[str, str]]:
    for paper_section, label, url in papers:
        if paper_section == section and matches(label):
            return label, url
    return None
