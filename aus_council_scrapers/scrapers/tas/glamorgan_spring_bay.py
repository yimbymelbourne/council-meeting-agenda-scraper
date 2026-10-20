import re
from typing import Optional

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper
from aus_council_scrapers.scrapers.tas.ionata_year_check import IonataYearCheck

# Glamorgan Spring Bay Council, on the Ionata meetings archive (see
# `aus_council_scrapers/ionata.py`). Ten cards a page, paged with `a.next`,
# so a year is two pages.
#
# The site was rebuilt in 2026 and only 2026 was carried over: the year
# filter offers 2026 alone, ?f_year=2025 returns no cards, and no archive of
# earlier papers is linked anywhere on the new site. So the history starts in
# January 2026, and that is the council's doing, not the scraper's.
#
# This theme splits a card differently from the other Ionata councils. The
# title is "Council Meeting | August 2026", the subtitle is the bare date, and
# the meeting type, start time and venue share one line:
# ".grid-item__description" = "Ordinary Council Meeting | 2:00pm | Council
# Chambers". The base class reads the date from the subtitle; the type, time
# and venue are read from that line here.
_DESCRIPTION_SEPARATOR = re.compile(r"\s*\|\s*")

# The time field defaults to midnight when nobody filled it in (the AGM card
# shows "12:00am"); no council meets then.
_PLACEHOLDER_TIME = re.compile(r"^12:00\s*am$", re.IGNORECASE)

# The description's first segment is the site's own meeting-type category
# ("Ordinary Council Meeting", "Special Meeting", "AGM").
_NAME_RULES = (
    (
        re.compile(r"annual general|\bagm\b|a\.g\.m", re.IGNORECASE),
        "Annual General Meeting",
    ),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Council Meeting"),
)


def _description(card: Tag) -> list[str]:
    element = card.select_one(".grid-item__description")
    if element is None:
        return []
    text = " ".join(element.get_text(" ", strip=True).split())
    return [part for part in _DESCRIPTION_SEPARATOR.split(text) if part]


@register_scraper
class GlamorganSpringBayScraper(IonataYearCheck, IonataMeetingsScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    # An empty listing for a year from here on, three months in, raises
    # (see `ionata_year_check.py`).
    archive_starts = 2026
    listing_url = "https://gsbc.tas.gov.au/council/meetings-and-minutes/"
    card_selector = "div.grid-item--meeting"
    title_selector = ".grid-item__title"
    date_selector = ".grid-item__subtitle"

    def __init__(self):
        super().__init__("glamorgan_spring_bay", "TAS", "https://gsbc.tas.gov.au")

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        text = " ".join([*_description(card)[:1], title])
        for pattern, name in _NAME_RULES:
            if pattern.search(text):
                return name
        return "Ordinary Council Meeting"

    def _parse_card(self, card: Tag, year: int) -> Optional[tuple]:
        found = super()._parse_card(card, year)
        if found is None:
            return None
        record, disputed = found
        parts = _description(card)
        if len(parts) >= 2 and not _PLACEHOLDER_TIME.match(parts[1]):
            record.time = parts[1]
        if len(parts) >= 3:
            record.location = parts[2]
        return record, disputed
