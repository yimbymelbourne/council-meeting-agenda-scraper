"""City of Playford.

A SimpleGov archive (see `aus_council_scrapers/craft.py`) laid out as an
accordion. Each `div.accordion--minutes` holds the date, a summary line
(`Ordinary Council — 22/09/26 — 7:00 pm at Council Chamber`, spaced dashes
and all) and its Agenda and Minutes links, which are in the HTML while
collapsed. Twenty meetings a page.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import BROWSER_USER_AGENT, register_scraper
from aus_council_scrapers.craft import (
    CraftArchiveScraper,
    CraftMeeting,
    clean_text,
    document_links,
    parse_listing_date,
    parse_listing_time,
)

_VENUE = re.compile(r"\bat\s+(.+)$")


@register_scraper
class PlayfordScraper(CraftArchiveScraper):
    listing_url = (
        "https://www.playford.sa.gov.au/council/council-and-committees/archive"
    )

    # The one council in this group whose AWS WAF lets a requests client
    # through, measured from a GitHub-hosted runner—but only a
    # browser-shaped one: the identifying User-Agent gets the 202 challenge.
    use_selenium = False
    user_agent = BROWSER_USER_AGENT

    def __init__(self):
        super().__init__("playford", "SA", "https://www.playford.sa.gov.au")

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        meetings = []
        for item in soup.select("div.accordion--minutes"):
            when = clean_text(item.select_one(".meetings__date"))
            date = parse_listing_date(when)
            if date is None:
                self.logger.warning(f"No date in listing row: {when!r}")
                continue

            summary_element = item.select_one(".meetings__data")
            summary = clean_text(summary_element)
            # The venue is usually a link to its page, but not always.
            venue_link = summary_element.find("a") if summary_element else None
            venue_match = _VENUE.search(summary)
            venue = clean_text(venue_link) or (
                venue_match.group(1) if venue_match else ""
            )

            meetings.append(
                CraftMeeting(
                    # The committee is everything before the first dash; the
                    # date that follows it is two-digit-year and redundant.
                    name=summary.split("—")[0].strip(),
                    date=date,
                    time=parse_listing_time(summary),
                    location=venue,
                    links=document_links(
                        item.select_one(".meetings__downloads") or item,
                        self.listing_url,
                    ),
                )
            )
        return meetings
