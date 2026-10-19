"""Where Resolve councils keep the papers Resolve does not have.

A Resolve tenant starts when the council moved to it (see `resolve.py`), so a
council's earlier meetings, and any body it never moved, are still on its
own website. This module reads the one shape of that website shared by more
than one of them: the meetings module of Granicus's OpenCities CMS, at
Burnside (its assessment panel, and Council before November 2022) and Moreton
Bay (before September 2024). Council-specific archives—Sutherland's Seamless
tables, Somerset's page of links—are read in the council's own module.

It is deliberately small. A fuller OpenCities base class is being built on
another branch (`opencities.py`); this one covers only what these two
councils need, and only through plain GETs:

* **The listing**, ten rows a page, newest first, filtered to one year by a
  GET parameter: `<listing>?dlv_OC%20CL%20Public%20Meetings=(dd_OC%20Year=
  2025)(pageindex=2)`. A row is a date, a meeting type and a `data-cvid`, with
  no document links. The site ignores a filter it does not recognise and
  serves the unfiltered list, so every row's year is checked.
* **One payload per meeting**, from `OCServiceHandler.axd`'s
  documentrenderer: the HTML the page's accordion loads, with each document
  under an `<h3>` saying what it is ("Agenda", "General minutes"). So a
  meeting costs a request, and the caller's `keep` pattern decides which
  rows are worth one.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Callable, Optional
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn

_RENDERER = (
    "/OCServiceHandler.axd?url=ocsvc/Public/meetings/documentrenderer"
    "&keywords=&cvid={cvid}"
)
_PAGE_COUNT = re.compile(r"seamless-pagination-count-(\d+)")

# A heading over the meeting's own agenda or minutes, as opposed to the
# papers that ride along with them: Moreton Bay files each report's
# attachments under "General supporting information".
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_NOT_THE_PAPER = re.compile(
    r"supporting|attachment|appendi|supplementary|addendum|late item",
    re.IGNORECASE,
)


def opencities_meetings(
    scraper: BaseScraper,
    listing_url: str,
    year: int,
    keep: re.Pattern,
    name: Callable[[str, str], str],
    list_name: str = "OC CL Public Meetings",
    meeting_type: Optional[str] = None,
    before: Optional[datetime.date] = None,
) -> list[ScraperReturn]:
    """One year of an OpenCities meeting listing, as meeting records.

    `keep` is matched against each row's meeting type before its payload is
    fetched. `name(meeting_type, title)` names a record from the row's type
    and the payload's title line. `meeting_type` filters the listing itself
    to one type, which saves listing pages where a year is mostly
    committees and workshops. `before` drops meetings on or after a date
    (the day the council moved to Resolve). A failed listing raises; a
    failed payload loses that meeting with a warning, and raises only when
    every payload failed.
    """
    filters = f"(dd_OC%20Year={year})"
    if meeting_type:
        filters = f"(dd_OC%20Meeting%20Type={quote(meeting_type)})" + filters
    rows = []
    page, pages = 1, 1
    while page <= pages:
        url = f"{listing_url}?dlv_{quote(list_name)}={filters}" + (
            f"(pageindex={page})" if page > 1 else ""
        )
        html = scraper.fetcher.fetch_with_requests(url)
        if page == 1:
            count = _PAGE_COUNT.search(html)
            pages = int(count.group(1)) if count else 1
        page_rows = _listing_rows(html)
        stray = [
            (date, kind)
            for date, kind, *_ in page_rows
            if date.year != year or (meeting_type and kind != meeting_type)
        ]
        if stray:
            raise RuntimeError(
                f"{scraper.council_name}: {url} listed {stray[0]}, outside its "
                f"filter; has the list name {list_name!r} changed?"
            )
        rows += page_rows
        page += 1

    results, failures = [], 0
    for date, kind, cvid, href in rows:
        if not keep.search(kind):
            continue
        if before and date >= before:
            continue
        payload_url = urljoin(listing_url, _RENDERER.format(cvid=cvid))
        try:
            payload = json.loads(scraper.fetcher.fetch_with_requests(payload_url))
        except Exception as e:
            failures += 1
            scraper.logger.warning(
                f"{scraper.council_name}: could not read {payload_url}: {e}"
            )
            continue
        record = _record(payload.get("html") or "", listing_url, date, href)
        if record:
            record.name = name(kind, record.name)
            results.append(record)

    if failures and not results:
        raise RuntimeError(
            f"{scraper.council_name}: every OpenCities meeting payload for "
            f"{year} failed ({failures})"
        )
    return results


def _listing_rows(html: str) -> list[tuple[datetime.date, str, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for container in soup.find_all("div", class_="accordion-list-item-container"):
        trigger = container.find("a", class_="accordion-trigger")
        date = container.find("span", class_="minutes-date")
        meeting_type = container.find("span", class_="meeting-type")
        if not (trigger and trigger.get("data-cvid") and date):
            continue
        rows.append(
            (
                parse_date(date.get_text(strip=True), dayfirst=True).date(),
                meeting_type.get_text(strip=True) if meeting_type else "",
                trigger["data-cvid"],
                trigger.get("href") or "",
            )
        )
    return rows


def _record(
    html: str, base_url: str, date: datetime.date, webpage_url: str
) -> Optional[ScraperReturn]:
    soup = BeautifulSoup(html, "html.parser")
    agenda_url = minutes_url = time = location = None

    for heading in soup.find_all("h3"):
        label = heading.get_text(" ", strip=True)
        if label == "Time":
            time = _after_heading(heading)
            continue
        if label == "Location":
            location = _after_heading(heading)
            continue
        if _NOT_THE_PAPER.search(label):
            continue
        pdf = _first_pdf(heading, base_url)
        if not pdf:
            continue
        if _AGENDA.search(label) and not agenda_url:
            agenda_url = pdf
        elif _MINUTES.search(label) and not minutes_url:
            minutes_url = pdf

    if not (agenda_url or minutes_url):
        # Listed ahead of time with nothing filed yet, or cancelled.
        return None

    # The payload opens with the meeting's own title line ("General Meeting
    # of the Moreton Bay City Council"), which the caller may use to tell a
    # special meeting from an ordinary one.
    title = soup.find("p")
    return ScraperReturn(
        name=title.get_text(" ", strip=True) if title else "",
        date=date.strftime("%Y-%m-%d"),
        time=_clock_time(time),
        webpage_url=webpage_url or base_url,
        agenda_url=agenda_url,
        minutes_url=minutes_url,
        download_url=agenda_url or minutes_url,
        location=location,
    )


def _after_heading(heading) -> Optional[str]:
    """The text a heading labels: the rest of its block, less any map link.

    Only the last line is kept. A location is sometimes preceded by notes
    for visitors—Moreton Bay's 2024 post-election meeting put parking
    directions and a campus map URL ahead of the venue."""
    block = heading.parent
    heading.extract()
    for link in block.find_all("a"):
        link.extract()
    for br in block.find_all("br"):
        br.replace_with("\n")
    for paragraph in block.find_all("p"):
        paragraph.append("\n")
    lines = [
        re.sub(r"https?://\S+", "", line).replace("\xa0", " ").strip()
        for line in block.get_text("").splitlines()
    ]
    lines = [line for line in lines if line]
    if not lines:
        return None
    return re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", lines[-1])).strip(" ,")


def _first_pdf(heading, base_url: str) -> Optional[str]:
    """The first PDF link after a heading and before the next one."""
    for element in heading.next_elements:
        if getattr(element, "name", None) == "h3":
            return None
        if getattr(element, "name", None) == "a":
            href = element.get("href") or ""
            if href.lower().split("?")[0].endswith(".pdf"):
                return urljoin(base_url, href)
    return None


def _clock_time(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    try:
        return parse_date(text).strftime("%I:%M %p").lstrip("0")
    except (ValueError, OverflowError):
        return None
