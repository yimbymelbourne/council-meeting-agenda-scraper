"""Starting point for a new council scraper.

Copy this to ``aus_council_scrapers/scrapers/<state>/<council>.py``, then work
through the TODOs. `tests/test_template.py` keeps this file honest, so what
you copy always matches the current API.

Before writing a parser, check whether the council uses a platform we already
handle — it is usually a ten-line subclass instead of a day's work:

    InfoCouncil (``*.infocouncil.biz``)
        from aus_council_scrapers.base import InfoCouncilScraper

        @register_scraper
        class ExampleScraper(InfoCouncilScraper):
            def __init__(self):
                super().__init__(
                    "example", "NSW",
                    "https://www.example.nsw.gov.au",
                    "https://example.infocouncil.biz/",
                )

    Others seen in this repo: docspublished.com.au (Parramatta), and
    OpenCities sites exposing ``OCServiceHandler.axd`` (Banyule, Strathfield).

Fetch the council's meeting page and look for those signatures first.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR


@register_scraper
class CouncilScraper(BaseScraper):
    # TODO: registering the class is not enough — import it in the state's
    # __init__.py too, or it never runs and is never tested. Nine scrapers in
    # this repo were written, decorated, and then forgotten because that step
    # was missed.
    def __init__(self):
        super().__init__(
            # TODO: snake_case slug, matching the Slug column in docs/councils.md
            council_name="council_name",
            state="VIC",
            base_url="https://www.example.vic.gov.au",
        )
        # Optional fallbacks used when a meeting does not state its own.
        self.default_time = None
        self.default_location = None

    def _meetings_url(self, year: int) -> str:
        # TODO: many councils publish one page per year. If this council has a
        # single page instead, drop the year loop in scraper() below.
        return f"{self.base_url}/council-meetings-{year}"

    def _parse_page(self, html: str, webpage_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperReturn] = []

        # TODO: replace with the council's actual markup.
        for row in soup.select(".meeting-row"):
            date = row.select_one(".date")
            if not date:
                continue

            # Agenda and minutes belong on the SAME record. Emitting one row
            # for the agenda and another for the minutes is a known failure
            # mode — scripts/scorecard.py reports it.
            agenda_url = None
            minutes_url = None
            for link in row.select("a[href]"):
                label = link.get_text(strip=True).lower()
                href = urljoin(self.base_url, link["href"])
                if "agenda" in label and not agenda_url:
                    agenda_url = href
                elif "minutes" in label and not minutes_url:
                    minutes_url = href

            # A meeting with neither document is not worth returning.
            if not agenda_url and not minutes_url:
                continue

            time_match = self.time_regex.search(row.get_text(" ", strip=True))

            results.append(
                ScraperReturn(
                    name=row.select_one(".title").get_text(strip=True),
                    date=date.get_text(strip=True),
                    time=time_match.group() if time_match else None,
                    webpage_url=webpage_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    # Deprecated, still required by consumers. Prefer the
                    # agenda; fall back to minutes for a past meeting.
                    download_url=agenda_url or minutes_url,
                    location=None,
                )
            )

        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results: list[ScraperReturn] = []

        # Use clock.current_year(), not datetime.now(): recorded fixtures pin
        # the clock to their recording date, so a scraper reading the real
        # clock starts requesting an unrecorded year every January and its
        # cassette fails for no reason anyone caused.
        for year in range(EARLIEST_YEAR, clock.current_year() + 3):
            url = self._meetings_url(year)
            try:
                html = self.fetcher.fetch_with_requests(url)
            except Exception as e:
                # Future years often 404 — that is expected, and the failure
                # is recorded so replay reproduces it.
                self.logger.debug(f"Could not fetch {url}: {e}")
                continue
            results.extend(self._parse_page(html, url))

        # For JavaScript-rendered pages use fetch_with_selenium(url) instead.
        # To drive a page (filters, paging), get_selenium_driver() is
        # recordable through execute_script(), page_source and get() only, and
        # self.fetcher.sleep(n) becomes a no-op during replay.

        if not results:
            # Returning an empty list is always a bug. Find out why rather
            # than shipping a scraper that quietly finds nothing.
            self.logger.warning(f"{self.council_name} found no meetings")

        self.logger.info(f"{self.council_name} found {len(results)} meetings")
        return results
