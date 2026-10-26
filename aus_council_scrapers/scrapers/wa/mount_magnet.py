import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.ionata import text_date
from aus_council_scrapers.sharepoint import file_share_download_url

_BASE_URL = "https://www.mtmagnet.wa.gov.au"
_MEETINGS_URL = f"{_BASE_URL}/council-meetings"
_MINUTES_URL = f"{_BASE_URL}/minutes"

# Shire of Mount Magnet (WA). A Squarespace site.
#
# A documented robots.txt exception. Every agenda and minutes is a SharePoint
# share link on mtmagnet.sharepoint.com, whose robots.txt is, in full
# (checked 26 Oct 2026):
#
#     User-Agent: *
#     Disallow: /
#
# The scraper itself requests only two pages of www.mtmagnet.wa.gov.au, which
# its robots.txt allows (it disallows /config, /search, /account, /api/,
# /static/ and some query strings, none of them used here, and sets no
# Crawl-delay). But council-alerts downloads every document URL a scraper
# emits, so emitting these links fetches the disallowed host. The maintainer
# decided on 26 Oct 2026 to do that anyway, because these papers are the
# council's official public record and its own pages link each one for every
# visitor. The load is one download per paper. Nothing else on the
# SharePoint host is requested, and robots.txt is still respected on every
# other host and path.
#
# The share link is a viewer page, so each is emitted in the form that
# returns the PDF itself; see `aus_council_scrapers/sharepoint.py`.
#
# **No 2026 papers are published** (checked 26 Oct 2026), so a production
# run fails by name. The minutes page's 2026 panel says "Links to 2026
# Council Meeting Agendas, Minutes and meeting recordings can now be found
# under the Council Meetings Heading in the Document Centre", but neither the
# Council Meetings page nor the Document Centre has any. The council has
# published nothing for 2026 that a scraper could find; the failure is the
# signal that this has changed, or has not.
#
# What there is: the Council Meetings page has a "Historical Agendas" and a
# "Historical Minutes" accordion, a panel per year to 2024; the Minutes page
# repeats the minutes and adds 2025. (The Agendas page repeats the
# historical agendas and is not read.) Agendas are linked only for 2023 and
# 2024; the 2020-2022 panels list the meetings with no links.
#
# Each panel is hand-typed paragraphs. A date and the paper are one line
# ("27 November 2024 - Ordinary Meeting", "Minutes of Ordinary Meeting 15
# December 2021"), or the date is a line of its own above the paper's link
# ("November 27 2024", then "Ordinary Meeting of Council"). An audit
# committee paper sometimes has no date at all and sits below the meeting
# held the same day; it takes the date of the line above. All five such
# papers were checked against their covers (the 18 June, 29 August and 26
# March 2025 minutes, the 28 August and 24 April 2024 agendas).
#
# The meeting is named by its link, so a link naming no meeting ("15
# December 2023", which repeats the next line's link) is not read, and nor
# are addenda and attachments.
_BODIES = (
    (re.compile(r"addendum|attachment", re.IGNORECASE), None),
    (re.compile(r"audit,?\s+risk", re.IGNORECASE), "Audit, Risk and Improvement Committee"),
    (re.compile(r"\baudit\b", re.IGNORECASE), "Audit Committee"),
    (re.compile(r"elector", re.IGNORECASE), "Annual Meeting of Electors"),
    (
        re.compile(r"ramelius|\brcbf\b", re.IGNORECASE),
        "Ramelius Community Benefit Fund Advisory Group",
    ),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Meeting of Council"),
    (re.compile(r"\bordinary\b", re.IGNORECASE), "Ordinary Meeting of Council"),
)
_AGENDA = re.compile(r"\bagendas?\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
# Squarespace pads empty lines with zero-width joiners.
_INVISIBLE = re.compile(r"[​-‍﻿]")

# Papers linked under the wrong meeting, each checked against its cover.
# "March 8 2023 – Special Meeting of Council" links the minutes of the audit
# committee that met the same day, which the next line links too.
_WRONG = {
    ("Special Meeting of Council", "2023-03-08", "minutes"),
}


def _clean(text: str) -> str:
    text = _INVISIBLE.sub("", text)
    # "26 February 202 0": a year split by the editor.
    text = re.sub(r"(?<!\d)(20\d)\s+(\d)(?!\d)", r"\1\2", text)
    return " ".join(text.split())


def _body(label: str) -> Optional[str]:
    for pattern, name in _BODIES:
        if pattern.search(label):
            return name
    return None


@register_scraper
class MountMagnetScraper(BaseScraper):
    def __init__(self):
        super().__init__("mount_magnet", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, page_url: str, page_kind: Optional[str], wanted: set[int]):
        """(body, date, kind, url) for each paper linked on one page."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(page_url), "html.parser")
        containers = soup.select(".accordion-items-container")
        if not containers:
            raise RuntimeError(f"{self.council_name}: no accordions at {page_url}")
        for container in containers:
            items = container.select("li.accordion-item")
            # "Historical Agendas" or "Historical Minutes" heads the
            # Council Meetings page's two accordions, as an item of its own.
            first_title = items[0].select_one(".accordion-item__title") if items else None
            header = first_title.get_text(" ", strip=True) if first_title else ""
            accordion_kind = (
                "minutes" if _MINUTES.search(header)
                else "agenda" if _AGENDA.search(header)
                else page_kind
            )
            for item in items:
                title = item.select_one(".accordion-item__title")
                year_text = title.get_text(" ", strip=True) if title else ""
                if not year_text.isdigit() or int(year_text) not in wanted:
                    continue
                yield from self._panel(item, int(year_text), accordion_kind, page_url)

    def _panel(self, item, year: int, accordion_kind: Optional[str], page_url: str):
        description = item.select_one(".accordion-item__description")
        if description is None:
            return
        carried: Optional[datetime.date] = None
        for line in description.find_all(["p", "li", "h3", "h4"], recursive=False):
            line_date = text_date(_clean(line.get_text(" ", strip=True)))
            if line_date is not None:
                carried = line_date
            for link in line.find_all("a", href=True):
                label = _clean(link.get_text(" ", strip=True))
                body = _body(label)
                if body is None:
                    self.logger.info(
                        f"{self.council_name}: {label!r} ({year}) is not a "
                        f"meeting's agenda or minutes; not read"
                    )
                    continue
                kind = (
                    "minutes" if _MINUTES.search(label)
                    else "agenda" if _AGENDA.search(label)
                    else accordion_kind
                )
                when = text_date(label) or carried
                if kind is None or when is None:
                    self.logger.warning(
                        f"{self.council_name}: {label!r} ({year}) has no "
                        f"{'date' if kind else 'paper type'}; left out"
                    )
                    continue
                if when.year != year:
                    self.logger.warning(
                        f"{self.council_name}: {label!r} is dated {when} in the "
                        f"{year} panel; left out"
                    )
                    continue
                url = file_share_download_url(link["href"])
                if url is None:
                    # 31 January 2024's agenda links a library view, not a
                    # share, which needs a signed-in session to open.
                    self.logger.warning(
                        f"{self.council_name}: the {kind} of the {body} of {when} "
                        f"links {link['href'][:120]}, which is not a SharePoint "
                        f"file share; left out"
                    )
                    continue
                yield body, when, kind, url, page_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        meetings: dict[tuple[str, datetime.date], dict[str, str]] = {}
        pages: list[tuple[str, Optional[str]]] = [
            (_MEETINGS_URL, None),
            (_MINUTES_URL, "minutes"),
        ]
        for page_url, page_kind in pages:
            for body, when, kind, url, found_on in self._papers(page_url, page_kind, wanted):
                if (body, when.isoformat(), kind) in _WRONG:
                    continue
                found = meetings.setdefault((body, when), {})
                if kind in found and found[kind] != url:
                    self.logger.warning(
                        f"{self.council_name}: two {kind} for the {body} of {when}; "
                        f"keeping the first"
                    )
                found.setdefault(kind, url)
                found.setdefault(f"{kind}_page", found_on)

        results = []
        for (body, when), found in sorted(meetings.items(), key=lambda m: (m[0][1], m[0][0])):
            agenda_url = found.get("agenda")
            minutes_url = found.get("minutes")
            results.append(
                ScraperReturn(
                    name=body,
                    date=when.isoformat(),
                    time=None,
                    webpage_url=found.get("agenda_page") or found["minutes_page"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # True of 2026 as of 26 Oct 2026; see the module comment.
            raise RuntimeError(
                f"{self.council_name}: no papers for {sorted(wanted)} on "
                f"{_MEETINGS_URL} or {_MINUTES_URL}; the council has not "
                f"published any for that year there"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
