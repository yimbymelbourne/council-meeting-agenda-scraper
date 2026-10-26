"""City of Whyalla.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The council
files every body's papers under one label, "Whyalla City Council Meetings":
council and special council meetings, but also the Audit Committee until
2022, the CEO Review Panel, the CEO Selection Panel of 2020, councillor
briefing sessions and informal gatherings. Grouped on that label alone, a
briefing session's agenda became a council meeting with no minutes, so the
body is read from each title instead (see `RelabellingLGASAScraper`).

**The audit committee.** From 2023 the Audit and Risk Committee's papers are
not in the collection at all. They are linked from a static page,
`AUDIT_PAGE`, which lists every agenda and minutes since 2020 as a
`li.generic-list__file` with the document's title as its link text ("Audit
and Risk Committee Meeting Agenda 9 October 2026 (PDF File, 21.8 MB)"). That
page is read too, through Selenium like the listing (the same Cloudflare
zone) and 20 s after it (the same host's crawl delay), and each link becomes
a document dated by its title. Its 2020-2022 links are the same assets as
the listing's, so they are read once. The audit committee's joint workshops
with the council ("Audit and Risk Committee Joint Workshop Agenda 8 October
2026") are kept as a body of their own, so a workshop's agenda is never
paired with a committee meeting's minutes.

The Upper Spencer Gulf Regional Assessment Panel, which Whyalla shares with
Port Augusta and Port Pirie, is not in this collection either: Whyalla links
its papers from another static page, and Port Augusta's and Port Pirie's
collections carry the same meetings.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.lgasa import (
    CHALLENGE_WAIT_SECONDS,
    _ASSET_PATH,
    _Listed,
    _title_date,
)
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper

AUDIT_PAGE = (
    "https://www.whyalla.sa.gov.au/our-city/council-and-committees/"
    "audit-committee-agenda-and-minutes"
)
AUDIT_COMMITTEE = "Audit and Risk Committee"

# The size note after each link's title: "(PDF File, 21.8 MB)".
_FILE_NOTE = re.compile(r"\s*\((?:PDF|Word|DOCX?)[^)]*\)\s*$", re.IGNORECASE)
# "2021.05.03- Audit Committee Minutes Final.pdf": a title that is the file
# name, dated year first.
_ISO_DOTTED = re.compile(r"\b(20\d\d)[.\-](\d\d)[.\-](\d\d)\b")
_WORKSHOP = re.compile(r"\bworkshop\b", re.IGNORECASE)
_AUDIT = re.compile(r"\baudit\b", re.IGNORECASE)


def _link_date(title: str) -> Optional[str]:
    stated = _title_date(title)
    if stated:
        return stated.isoformat()
    match = _ISO_DOTTED.search(title)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    return None


def _audit_documents(page: str) -> list[_Listed]:
    """The audit page's document links, as listed documents."""
    soup = BeautifulSoup(page, "html.parser")
    documents = []
    for link in soup.select("li.generic-list__file .generic-list__title a[href]"):
        path = _ASSET_PATH.search(urllib.parse.unquote(link["href"]))
        if not path:
            continue
        asset_type, asset_id, filename = path.groups()
        title = _FILE_NOTE.sub("", link.get_text(" ", strip=True))
        if not _AUDIT.search(title):
            continue
        documents.append(
            _Listed(
                asset_id=asset_id,
                title=title,
                filename=filename,
                asset_type=asset_type,
                committee=(
                    f"{AUDIT_COMMITTEE} Workshop"
                    if _WORKSHOP.search(title)
                    else AUDIT_COMMITTEE
                ),
                date=_link_date(title),
            )
        )
    return documents


@register_scraper
class WhyallaScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.whyalla.sa.gov.au/our-city/council-and-committees/"
        "whyalla-city-council-meetings",
        AUDIT_PAGE,
    )

    title_labels = frozenset({"Whyalla City Council Meetings"})
    drop_stray_years = True
    title_bodies = (
        # One body with the static page's, so the 2020-2022 documents the
        # listing also carries group with them.
        (re.compile(r"\baudit\b", re.IGNORECASE), AUDIT_COMMITTEE),
        (re.compile(r"\bCEO Selection\b", re.IGNORECASE), "CEO Selection Panel"),
        # "CEO Review Panel Meeting", "Chief Executive Officer's Review
        # Panel", "CEO Performance Review Committee": one body, renamed.
        (
            re.compile(r"\bCEO\b|\bChief Executive Officer", re.IGNORECASE),
            "CEO Review Panel",
        ),
        (re.compile(r"briefing|informal gathering", re.IGNORECASE), "Briefing Session"),
        # "Council Members Mandatory Training - 1 May 2023" is a training
        # day, not a meeting.
        (re.compile(r"\btraining\b", re.IGNORECASE), None),
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21 s
    # (2 Selenium page loads, one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("whyalla", "SA", "https://www.whyalla.sa.gov.au")

    def _read_listing(self, listing_url: str, earliest_year: int) -> list[_Listed]:
        if listing_url != AUDIT_PAGE:
            return super()._read_listing(listing_url, earliest_year)
        documents = _audit_documents(self._fetch_audit_page())
        if not documents:
            # The page always lists the committee's papers; none means the
            # layout changed, not that the committee stopped meeting.
            raise RuntimeError(f"{AUDIT_PAGE}: no document links found")
        return documents

    def _records(self, meetings) -> list[ScraperReturn]:
        records = super()._records(meetings)
        for record in records:
            # The audit page lists every one of the committee's papers since
            # 2020, including those the listing also carries.
            if (record.name or "").endswith(
                (AUDIT_COMMITTEE, f"{AUDIT_COMMITTEE} Workshop")
            ):
                record.webpage_url = AUDIT_PAGE
        return records

    def _fetch_audit_page(self) -> str:
        """The audit page through Chrome, retried once, as `_fetch_page`
        fetches a listing; it waits for the page's document list instead."""
        last_error: Optional[Exception] = None
        for attempt in range(2):
            self._wait_for_crawl_delay(AUDIT_PAGE)
            try:
                return self.fetcher.fetch_with_selenium(
                    AUDIT_PAGE,
                    wait_time=CHALLENGE_WAIT_SECONDS,
                    wait_condition=EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "li.generic-list__file")
                    ),
                )
            except Exception as error:
                last_error = error
                self.logger.warning(
                    f"{self.council_name}: audit page failed "
                    f"(attempt {attempt + 1}/2): {type(error).__name__}: {error}"
                )
                self.fetcher.restart_driver()
        raise last_error
