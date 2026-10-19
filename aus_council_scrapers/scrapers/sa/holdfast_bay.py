"""City of Holdfast Bay.

A SimpleGov archive (see `aus_council_scrapers/craft.py`), twenty meetings a
page, upcoming ones included. Each meeting is a summary row (date, venue,
committee) followed by a hidden expand row holding its documents; the two are
paired by the Alpine index in the button's `@click` and the panel's
`x-show="expand == N"`, which is sturdier than trusting the next sibling.

Link text here is free text ("Council Agenda and Reports 9 December 2025",
"Confidential Release 18 1 Alwyndor Update ..."), so documents are sorted by
the folder they are filed in—`agendas/`, `minutes/`, `attachments/`. The
one trap in that is the notice of cancellation, which Holdfast files under
`agendas/`; `classify_document` drops it.

One known council error is left as published: the Alwyndor Management
Committee of 21 May 2020 has the 16 April 2020 minutes (its agenda item 5.1)
in its minutes folder. No rule catches it without losing real minutes. The
item-number prefix ("5.1-...") also marks the correct minutes of 29 July
2021 and 27 January 2022, and a filename date that differs from the meeting
date marks dozens of correct papers that name a release or amendment date.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import (
    CraftArchiveScraper,
    CraftMeeting,
    clean_text,
    document_links,
    parse_listing_date,
    parse_listing_time,
)

_EXPAND_INDEX = re.compile(r"expand\s*==\s*(\d+)")


@register_scraper
class HoldfastBayScraper(CraftArchiveScraper):
    listing_url = "https://www.holdfast.sa.gov.au/council/council-committees/archive"

    # From a GitHub-hosted runner, plain requests get the AWS WAF challenge
    # whatever the User-Agent; headless Chrome passes unmodified.

    def __init__(self):
        super().__init__("holdfast_bay", "SA", "https://www.holdfast.sa.gov.au")

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        panels = {}
        for element in soup.find_all("tr", attrs={"x-show": True}):
            match = _EXPAND_INDEX.search(element["x-show"])
            if match:
                panels[match.group(1)] = element

        meetings = []
        for cell in soup.select('td[data-th="Meeting Date"]'):
            row = cell.find_parent("tr")
            when = clean_text(cell)
            date = parse_listing_date(when)
            if date is None:
                self.logger.warning(f"No date in listing row: {when!r}")
                continue

            button = row.find("button", attrs={"@click": True})
            match = _EXPAND_INDEX.search(button["@click"]) if button else None
            panel = panels.get(match.group(1)) if match else None

            # The venue is the second cell, which has no data-th label.
            cells = row.find_all("td", recursive=False)
            location = clean_text(cells[1]) if len(cells) > 1 else ""

            meetings.append(
                CraftMeeting(
                    name=clean_text(row.select_one('td[data-th="Committee"]')),
                    date=date,
                    time=parse_listing_time(when),
                    location=location,
                    links=document_links(panel, self.listing_url) if panel else [],
                )
            )
        return meetings
