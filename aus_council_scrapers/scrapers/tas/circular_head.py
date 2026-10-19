"""Circular Head Council (TAS).

Like Derwent Valley, a Tasmanian council hosted on the LGA SA shared Squiz
Matrix platform, with the same listing page, robots.txt and Cloudflare
front; see `LGASAFunnelbackScraper`.

Everything is filed under "Agendas and Minutes" or "Agendas & Minutes",
both of which the base class reads as the council itself. Titles name only
the month ("Agenda OCT 2026"), or nothing at all ("Minutes"); the meeting
date comes from the listing's meeting-date field, which is the full date
(the uploaded file names agree: "20261015-OPEN-Council-Meeting-Agenda.pdf").
The AGM is held on a separate evening and is named from its titles.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_regional import RegionalLGASAScraper


@register_scraper
class CircularHeadScraper(RegionalLGASAScraper):
    listing_urls = ("https://www.circularhead.tas.gov.au/our-council/agendas",)

    def __init__(self):
        super().__init__("circular_head", "TAS", "https://www.circularhead.tas.gov.au")
