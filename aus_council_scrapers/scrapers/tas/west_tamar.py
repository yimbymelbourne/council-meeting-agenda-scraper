import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper
from aus_council_scrapers.scrapers.tas.ionata_year_check import IonataYearCheck

# West Tamar Council, on the Ionata meetings archive (see
# `aus_council_scrapers/ionata.py`). A filtered year is one page of about 13
# cards, newest first, and the current year includes the next meeting once
# its agenda is up. Each card has a "20 October 2026 - 1:30pm" tag, a title,
# the venue and links labelled exactly "Agenda", "Minutes" and "Livestream".
#
# The archive starts in 2024: the year filter offers 2024-2026, and any other
# year returns the page with no cards. The 2023 minutes are on a separate
# "archived minutes" page, but each is dated only by month ("2023-12 –
# Council Minutes – December 2023"), with no agendas, so they are left out
# rather than given an invented day.
#
# Filenames carry a YYYY-MM month prefix that is sometimes wrong: the
# October 2025 agenda is uploaded as 2025-09-Ordinary-Council-Meeting-
# Agenda.pdf (in the uploads/2025/10/ folder), but the file is the 21 October
# agenda. The base class only lets a filename outvote the card when it names
# a full date, which these prefixes do not, so the card wins—correctly.
#
# Titles are "October 2026 – Ordinary Council Meeting" or "Annual General
# Meeting 2025"; the type is read from keywords.
_NAME_RULES = (
    (re.compile(r"annual general|\bagm\b", re.IGNORECASE), "Annual General Meeting"),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Council Meeting"),
)


@register_scraper
class WestTamarScraper(IonataYearCheck, IonataMeetingsScraper):
    # An empty listing for a year from here on, three months in, raises
    # (see `ionata_year_check.py`).
    archive_starts = 2024
    listing_url = "https://www.wtc.tas.gov.au/council/meetings-agendas-minutes/"
    card_selector = "div.grid-item"
    title_selector = ".grid-item__title"
    date_selector = ".grid-item__tag"
    location_selector = ".grid-item__subtitle"

    def __init__(self):
        super().__init__("west_tamar", "TAS", "https://www.wtc.tas.gov.au")

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        for pattern, name in _NAME_RULES:
            if pattern.search(title):
                return name
        return "Ordinary Council Meeting"
