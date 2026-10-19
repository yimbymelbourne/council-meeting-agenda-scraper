"""Berri Barmera Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. Council
meetings are on one page and the Riverland Regional Assessment Panel on
another; the panel decides development applications for Berri Barmera,
Loxton Waikerie and Renmark Paringa, and each of them republishes its
papers. Berri Barmera's other committees each have a page of their own and
are not read: each costs a Selenium load and a 20 s crawl delay.

Workshops, briefings and informal gatherings are filed under the council's
own label and titled like its papers, and released confidential papers are
filed days away from their meeting, so both are dropped by title; see
`RegionalLGASAScraper`.

The two special meetings of 1 June 2021, at 5.30 pm and 7 pm, are titled
alike: "Agenda 1 June 2021" and "Agenda 1 June 2021 (7:00pm)", minutes
"(1)" and "(2)". `RegionalLGASAScraper` pairs them by the numbered minutes
and the one stated start time (see `_pair_numbered_sittings`).
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.lgasa_regional import (
    CONFIDENTIAL_TITLES,
    INFORMAL_TITLES,
    RegionalLGASAScraper,
)

RRAP = "Riverland Regional Assessment Panel"


@register_scraper
class BerriBarmeraScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.berribarmera.sa.gov.au/your-council/council-meetings/agenda",
        "https://www.berribarmera.sa.gov.au/your-council/committee-meetings/"
        "regional-assessment-panel",
    )

    # The council's own label has changed over the years; all three mean
    # the full council. "- Agenda and Minutes" is stripped by the base
    # class, but the dash before it is not.
    committee_names = {
        "Full Council - Agenda and Minutes": COUNCIL_MEETING,
        "Council - Agenda and Minutes": COUNCIL_MEETING,
        "Regional Assessment Panel": RRAP,
    }

    # Informal gatherings, and confidential papers once released: Berri
    # Barmera files those a few days from the meeting they belong to, where
    # each became a meeting of its own. No public agenda or minutes here is
    # titled confidential or released.
    skip_titles = re.compile(
        f"{INFORMAL_TITLES.pattern}|{CONFIDENTIAL_TITLES.pattern}", re.IGNORECASE
    )

    # One production year, measured 20 Oct 2026 from a home IP: 22 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    def __init__(self):
        super().__init__("berri_barmera", "SA", "https://www.berribarmera.sa.gov.au")
