"""District Council of Orroroo Carrieton.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and, for the
title corrections, `TitleCorrectedLGASAScraper`. The council has no page over
the whole collection: the agendas-and-minutes page lists council and special
council meetings only, and the Audit & Risk Management and Asset Management
committees have a page each, which would cost one more request, 20 s apart,
apiece. Neither is read.

Development applications go to the Flinders Regional Assessment Panel. Its
papers are linked from a plain content page (/development-and-health/
frdap-meetings), not a listing, with PDFs only on the council's Cloudflare
domain, so it is not read here.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa._lgasa_titles import TitleCorrectedLGASAScraper


@register_scraper
class OrrorooCarrietonScraper(TitleCorrectedLGASAScraper):
    listing_urls = (
        "https://www.orroroo.sa.gov.au/about-council/council-minutes-and-agendas",
    )

    # The page's name in reverse; the base class understands "Agendas and
    # Minutes" but not this.
    committee_names = {"Minutes & Agendas": COUNCIL_MEETING}

    # The base class follows the file name when it names a different paper
    # from the title. One exception here: its "Council-Meeting-Agenda-23-April-2025-Public.pdf" opens "MINUTES. Council Meeting. Wednesday 23rd April".
    title_kinds = ((r"^Council Meeting Minutes 23 April 2205$", "minutes", 0),)

    def __init__(self):
        super().__init__("orroroo_carrieton", "SA", "https://www.orroroo.sa.gov.au")
