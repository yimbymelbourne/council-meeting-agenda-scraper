"""Wudinna District Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. The agendas-and-minutes page
lists the whole collection, every committee included, in one request.

Council meetings sit under three labels over the years: "Council Meetings"
(to 2020), "Minutes & Agendas" (2019-2021) and "Ordinary Meeting of
Council" (2021 on). The base class reads only the first as the council
itself; the other two are mapped here.

Titles name only the month ("October Agenda 2026", "September 2026
Minutes"). The day is the meeting date the council filed in the listing.

The Eyre Peninsula Regional Assessment Panel is the regional panel that
assesses development applications for Wudinna and its neighbours (Kimba,
Elliston, Cleve and others publish the same panel's papers). It is kept,
because it is where Wudinna's planning decisions are made.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper


@register_scraper
class WudinnaScraper(TitleCorrectedLGASAScraper):
    listing_urls = ("https://www.wudinna.sa.gov.au/our-council/minutes-and-agendas",)

    committee_names = {
        "Ordinary Meeting of Council": COUNCIL_MEETING,
        # The page's name in reverse ("Agendas and Minutes" is already
        # understood), used for council meetings from late 2019 to early 2021.
        "Minutes & Agendas": COUNCIL_MEETING,
        # Filed as "Audit Committee" to 2024 and "Audit & Risk Committee"
        # since 2025: one committee, under the name it has now.
        "Audit Committee": "Audit & Risk Committee",
    }

    def __init__(self):
        super().__init__("wudinna", "SA", "https://www.wudinna.sa.gov.au")
