"""Burnie City Council (north-west Tasmania).

Two sources on the council's OpenCities site, and neither is complete alone:

* **The meetings module** at ``/Council/Council-Meetings/Agenda-and-Minutes``
  ("OC CL Public Meetings"). It holds only the latest two meetings—22
  September and 27 October 2026 in October 2026—each with its "Open Agenda"
  and "Open Minutes" in the renderer payload. Its year filter offers 2018–
  2026, but every year before 2026 returns no rows. This is the only place an
  agenda is linked, so it is how upcoming agendas are caught.
* **"Past Council Minutes"**, a static page with every open-session minutes
  PDF from January 2020, grouped under "2026 Open Minutes", "2025 Open
  Minutes" and so on, each link labelled "Council Minutes - 22 September 2026
  (PDF, 15MB)" (or "... - Annual General Meeting").

So meetings older than the module's two carry minutes only. Their agendas are
on the same file store under predictable names
(``open-session-agenda-ordinary-meeting-of-council-25-august-2026.pdf``
answered as a PDF in October 2026), but no page links them, so they are not
guessed at here. In October 2026 that left one agenda (22 September 2026)
across 87 meetings since 2020. The scorecard's Agendas column counts
``download_url``, which falls back to the minutes, so it shows all 87; the
real agenda coverage is the module's two meetings.

The two sources overlap on the latest meeting. They are joined on date and
meeting type, the module's papers winning where both have one.

Burnie's papers are all the Ordinary Meeting of Council or the Annual General
Meeting (filenames ``open-session-certified-minutes-ordinary-meeting-of-
council-…``, ``certified-minutes-annual-general-meeting-…``); the module's
own meeting type is just "Meeting", so the name is read from the filenames.

The site is on Granicus's Akamai edge (``X-Akamai-Transformed``), like the
other OpenCities councils in production, and answered plain requests with no
challenge from a home connection.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

_BASE_URL = "https://www.burnie.tas.gov.au"
_PAST_MINUTES_URL = f"{_BASE_URL}/Council/Council-Meetings/Past-Council-Minutes"

# "Council Minutes - 22 September 2026 (PDF, 15MB)", "Council Minutes - 9
# December 2025 - Annual General Meeting (PDF, 311KB)".
_PAST_LABEL = re.compile(
    r"^council minutes\s*[-–—]\s*(?P<date>\d{1,2}\s+[a-z]+\s+\d{4})"
    r"(?:\s*[-–—]\s*(?P<body>[^()]+?))?\s*(?:\(|$)",
    re.IGNORECASE,
)

_NAME_RULES = (
    (re.compile(r"annual[\s-]+general", re.IGNORECASE), "Annual General Meeting"),
    (re.compile(r"special", re.IGNORECASE), "Special Council Meeting"),
)


def _meeting_name(*texts: Optional[str]) -> str:
    text = " ".join(t for t in texts if t)
    for pattern, name in _NAME_RULES:
        if pattern.search(text):
            return name
    return "Ordinary Council Meeting"


def _filename(url: Optional[str]) -> Optional[str]:
    return urlparse(url).path.rsplit("/", 1)[-1] if url else None


@register_scraper
class BurnieScraper(OpenCitiesMeetingsScraper):
    list_name = "OC CL Public Meetings"
    # "Open Agenda - 22 September 2026" / "Open Minutes - 22 September 2026"
    # in one flat list.
    papers_by = "link_text"
    # The 2026-filtered page carries the same year dropdown as the bare one
    # (checked October 2026), so production asks for its year directly.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "burnie",
            "TAS",
            f"{_BASE_URL}/Council/Council-Meetings/Agenda-and-Minutes",
        )

    def meeting_name(self, row: ListingRow, content: BeautifulSoup, papers: dict) -> str:
        return _meeting_name(_filename(papers.get("agenda")), _filename(papers.get("minutes")))

    def _past_minutes(self) -> list[ScraperReturn]:
        # Required: it carries every minutes PDF but the latest, so a failure
        # here must fail the council rather than return two meetings.
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_PAST_MINUTES_URL), "html.parser"
        )
        wanted = self._wanted_years()
        results: list[ScraperReturn] = []
        labelled = 0
        for link in soup.find_all("a", href=True):
            url = urljoin(_BASE_URL, link["href"].strip())
            if not urlparse(url).path.lower().endswith(".pdf"):
                continue
            label = " ".join(link.get_text(" ", strip=True).split())
            match = _PAST_LABEL.match(label)
            if not match:
                continue
            labelled += 1
            date = parse_date(match.group("date"), dayfirst=True).date()
            if date.year not in wanted or date.year < EARLIEST_YEAR:
                continue
            results.append(
                ScraperReturn(
                    name=_meeting_name(match.group("body"), _filename(url)),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_PAST_MINUTES_URL,
                    minutes_url=url,
                    download_url=url,
                )
            )
        if not labelled:
            raise RuntimeError(f"burnie: no minutes links recognised on {_PAST_MINUTES_URL}")
        return results

    def scraper(self) -> list[ScraperReturn]:
        module = super().scraper()
        for record in module:
            # The listing row's "22 September 2026", made comparable with the
            # past-minutes records.
            record.date = parse_date(record.date, dayfirst=True).date().isoformat()
        merged: dict[tuple[str, str], ScraperReturn] = {
            (record.name, record.date): record for record in module
        }
        for record in self._past_minutes():
            existing = merged.get((record.name, record.date))
            if existing is None:
                merged[(record.name, record.date)] = record
            elif not existing.minutes_url:
                existing.minutes_url = record.minutes_url
                existing.download_url = existing.agenda_url or existing.minutes_url
        results = sorted(merged.values(), key=lambda r: (r.date, r.name), reverse=True)
        if not results:
            self.logger.warning("burnie: no meetings with papers in the wanted years")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
