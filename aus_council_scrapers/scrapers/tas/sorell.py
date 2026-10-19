import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.ionata import IonataMeetingsScraper

# Sorell Council. A filtered year fits on one page (24-36 cards), oldest
# first, and the current year includes the next meeting once its agenda is up.
#
# Titles are typed by hand and drift from year to year — "Council Meeting
# January", "Sorell Planning Authority (SPA) Agenda – Tuesday 12 November
# 2024", "Sorell Planning Planning Authority 4 March 2021" — so the meeting
# type is read from keywords. Development Assessment Special Committee is
# checked before "special", which it also contains.
_NAME_RULES = (
    (re.compile(r"annual general|\bagm\b", re.IGNORECASE), "Annual General Meeting"),
    (
        re.compile(r"development assessment", re.IGNORECASE),
        "Development Assessment Special Committee",
    ),
    (
        re.compile(r"planning authority|\bspa\b", re.IGNORECASE),
        "Sorell Planning Authority Meeting",
    ),
    (re.compile(r"\bspecial\b", re.IGNORECASE), "Special Council Meeting"),
)


@register_scraper
class SorellScraper(IonataMeetingsScraper):
    listing_url = "https://www.sorell.tas.gov.au/meetings-minutes/"
    card_selector = "div.grid-page"
    title_selector = ".grid-page__title"
    # Date and location are two divs of the same class, in that order.
    date_selector = ".grid-page__date:nth-of-type(1)"
    location_selector = ".grid-page__date:nth-of-type(2)"

    def __init__(self):
        super().__init__("sorell", "TAS", "https://www.sorell.tas.gov.au")

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        # Sorell's titles name every meeting type it holds, so the filenames
        # are not consulted.
        for pattern, name in _NAME_RULES:
            if pattern.search(title):
                return name
        return "Council Meeting"
