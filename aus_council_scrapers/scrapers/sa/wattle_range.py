"""Wattle Range Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and
`RegionalLGASAScraper`. The council has no page over the whole collection:
each committee page lists that committee only. Council meetings are on one
page, and the Regional Assessment Panel—the Limestone Coast Southern panel
since 2022, and the Council Assessment Panel before it—on another. Audit
and Risk and the s 41 hall and reserve committees are not read: each page
costs a Selenium load and a 20 s crawl delay, and the planning panel is the
one that decides development applications.

Papers filed beside the agenda and minutes carry a bracketed note in their
title: "13 Oct 2026 Agenda [Item 15.2.3 - Updated Attachment ]", "29 Jun
2023 Agenda [Tabled Correspondence - ...]", "19 May 2026 Agenda [Special]
[Late Item 6.2.3 Report & Attachment]". Those naming an item, a tabled paper
or a late report are never the agenda or minutes and are dropped, because
when one is misfiled on a day of its own it becomes a meeting that never
happened. "[Special]" is kept, and so is a bare "[Confidential]" or
"[Special Confidential]": the 27 July 2021 special meeting's only agenda
("Special-Council-Agenda-and-Papers-Public-Copy.pdf") and the 29 January
2020 assessment panel's only minutes are titled that way, and the base
class already ranks such a paper behind a clean one.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper


@register_scraper
class WattleRangeScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.wattlerange.sa.gov.au/our-council/meetings-and-gatherings/"
        "councilmeetings",
        "https://www.wattlerange.sa.gov.au/our-council/committees/rap",
    )

    skip_titles = re.compile(r"\[[^\]]*\b(?:items?|tabled|late)\b", re.IGNORECASE)

    # One production year, measured 20 Oct 2026 from a home IP: 22 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    def __init__(self):
        super().__init__("wattle_range", "SA", "https://www.wattlerange.sa.gov.au")
