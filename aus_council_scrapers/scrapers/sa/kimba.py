"""District Council of Kimba.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. Kimba has no page over the
whole collection—/council/agendas-and-minutes is a landing page and each
committee page lists one committee—so the council's page and the Eyre
Peninsula Regional Assessment Panel's are read, 20 s apart. The panel is the
regional body that assesses Kimba's development applications. The Audit &
Risk, Australia Day, Bushfire Management Advisory and Tourism committee
pages would cost one more request each and are not read.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper

_INFORMATION_SESSION = "Information Session"


@register_scraper
class KimbaScraper(TitleCorrectedLGASAScraper):
    listing_urls = (
        "https://www.kimba.sa.gov.au/council/agendas-and-minutes/council-agendas-and-minutes",
        "https://www.kimba.sa.gov.au/council/agendas-and-minutes/Eyre-Peninsula-Regional-Assessment-Panel-minutes-and-agendas",
    )

    committee_names = {
        "Eyre Peninsula Regional Assessment Panel Minutes & Agendas": (
            "Eyre Peninsula Regional Assessment Panel"
        ),
    }

    # Council workshops are held the same day as most council meetings and
    # filed under the same label with their own agenda and minutes; grouped
    # with the meeting, the workshop's papers were chosen as the meeting's.
    title_bodies = (
        (re.compile(r"\bworkshop\b", re.IGNORECASE), "Council Workshop"),
        (re.compile(r"\binformation session\b", re.IGNORECASE), _INFORMATION_SESSION),
    )
    # "Notice of Information Session - Kimba Brand Strategy - 23rd August 2023"
    # is that session's only paper.
    notice_committees = frozenset({_INFORMATION_SESSION})

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("kimba", "SA", "https://www.kimba.sa.gov.au")
