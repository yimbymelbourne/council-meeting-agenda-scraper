import datetime
import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper
from aus_council_scrapers.scrapers.tas.ionata_year_check import IonataYearCheck
from aus_council_scrapers.sharepoint import file_share_download_url

# Huon Valley Council. An Ionata meetings archive: cards filtered server-side
# by `f_year` (2014 onwards), newest first, 14-18 cards a year on one page, so
# a production year is one request. The current year lists the rest of the
# year's meetings ahead of time, with no links until papers are up.
#
# A documented robots.txt exception. The papers are SharePoint share links,
# on huonvalleycouncil.sharepoint.com (team site `hvcwebsite`) and on
# huonvalleycouncil-my.sharepoint.com (council staff OneDrives). Both hosts'
# robots.txt is, in full (checked 26 Oct 2026):
#
#     User-Agent: *
#     Disallow: /
#
# The scraper itself requests only the listing on www.huonvalley.tas.gov.au,
# whose robots.txt disallows only /wp/wp-admin/ and sets no Crawl-delay. But
# council-alerts downloads every document URL a scraper emits, so emitting
# these links fetches the disallowed hosts. The maintainer decided on 26 Oct
# 2026 to do that anyway, because these papers are the council's official
# public record and its own page links each one for every visitor. The load
# is one download per paper. Nothing else on the SharePoint hosts is
# requested.
#
# Minutes first, because most agendas cannot be emitted. Every minutes link
# is a *file* share, which `aus_council_scrapers/sharepoint.py` turns into a
# download.aspx URL that returns the PDF itself. Most agendas are *folder*
# shares (the agenda beside its attachments), which open only with a guest
# cookie and have no URL a plain client can download; those are left out.
# Agendas linked as file shares (1-9 a year: 1 of 11 linked in 2026, 2 of 14
# in 2025, 9 of 14 in 2024, checked 26 Oct 2026) are emitted. So a meeting
# appears once its minutes are up, or earlier only when its agenda is a file
# share: most upcoming meetings are not emitted at all.
#
# Papers from January to August 2020, and March and April 2021, are on Google
# Drive (minutes as files, agendas mostly as folders). Drive's robots.txt
# disallows `/uc`, the direct download, and that host is not part of the
# SharePoint decision, so they are left out; those meetings are missing.
#
# The card's header holds the date alone; its description holds the meeting
# type, the time and the place, "Ordinary Meeting | 6:00pm | Council
# Chambers". Before mid-2024 the time is a 12:00am placeholder and before 2022
# the type is blank, so the name falls back to the title ("December 2019
# Council Meeting – AGM", "March 2021 AGM (2019-2020)", "June 2019 Council
# Meeting – Special").
_LISTING_URL = (
    "https://www.huonvalley.tas.gov.au/council-governance/meetings-agendas-minutes/"
)

_PLACEHOLDER_TIME = re.compile(r"^12:00\s*am$", re.IGNORECASE)
_TIME = re.compile(r"^\d{1,2}(?::\d\d)?\s*[ap]m$", re.IGNORECASE)

_NAME_RULES = (
    (re.compile(r"annual general|\bagm\b", re.IGNORECASE), "Annual General Meeting"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Meeting of Council"),
)


@register_scraper
class HuonValleyScraper(IonataYearCheck, IonataMeetingsScraper):
    listing_url = _LISTING_URL
    card_selector = "div.grid-item-alt"
    title_selector = ".grid-item-alt__title"
    date_selector = ".grid-item-alt__header"
    # The first year whose cards carry a paper that can be emitted (2020's
    # September-December minutes). Earlier years are not requested anyway.
    archive_starts = 2020

    def __init__(self):
        super().__init__("huon_valley", "TAS", "https://www.huonvalley.tas.gov.au")

    def document_url(self, href: str) -> Optional[str]:
        # A SharePoint file share, as its direct download; a folder share,
        # Google Drive link or anything else is not a document URL.
        return file_share_download_url(href)

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        meeting_type, _, _ = self._description(card)
        for pattern, name in _NAME_RULES:
            if pattern.search(meeting_type or "") or pattern.search(title):
                return name
        return "Ordinary Meeting of Council"

    @staticmethod
    def _description(card: Tag) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """The card's (type, time, location), each None when blank."""
        element = card.select_one(".grid-item-alt__description")
        if element is None:
            return None, None, None
        parts = [" ".join(p.split()) for p in element.get_text(" ").split("|")]
        meeting_type = parts[0] or None if parts else None
        time = location = None
        rest = parts[1:]
        if rest and _TIME.match(rest[0]):
            time = rest.pop(0)
            if _PLACEHOLDER_TIME.match(time):
                time = None
        if rest:
            location = " | ".join(rest) or None
        return meeting_type, time, location

    def _parse_card(
        self, card: Tag, year: int
    ) -> Optional[tuple[ScraperReturn, dict[str, datetime.date]]]:
        found = super()._parse_card(card, year)
        if found is None:
            return None
        record, disputed = found
        _, record.time, record.location = self._description(card)
        return record, disputed
