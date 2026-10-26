"""District Council of Elliston.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. Each page under
/council-documents lists one committee, so the council's page and the
assessment panel's are read, 20 s apart. The Section 41 committees (Audit and
Risk, CEO Selection, Bramfield Basin & Elliston Water) would cost one more
request each and are not read.

The panel page carries two bodies under one label: Elliston's own Council
(Development) Assessment Panel until 2018, and the Eyre Peninsula Regional
Assessment Panel, which has assessed its development applications since 2020.
The title says which.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper

_PANEL_LABEL = (
    "Regional Assessment Panel and Council Assessment Panel Minutes & Agendas"
)


@register_scraper
class EllistonScraper(TitleCorrectedLGASAScraper):
    listing_urls = (
        "https://www.elliston.sa.gov.au/council-documents/council-meeting-agendas-and-minutes",
        "https://www.elliston.sa.gov.au/council-documents/council-assessment-panel-minutes-and-agendas",
    )

    committee_names = {_PANEL_LABEL: "Council Assessment Panel"}

    title_bodies = (
        # "EPRAP Meeting Agenda", once "EPRAG"; Kimba's spell it "ERAP".
        (
            re.compile(r"\bE?PRA[PG]\b|\bregional assessment\b", re.IGNORECASE),
            "Eyre Peninsula Regional Assessment Panel",
        ),
        # A released confidential item of the Audit Committee, filed under the
        # council label: not a council meeting, and not that committee's
        # minutes either.
        (re.compile(r"\baudit committee\b", re.IGNORECASE), None),
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (two
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__("elliston", "SA", "https://www.elliston.sa.gov.au")
