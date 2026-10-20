"""Southern Mallee District Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. Only council papers are filed
here, under "Council Agendas and Minutes" until 2025 and "Council Meetings"
since; the base class reads both as the council itself.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class SouthernMalleeScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.southernmallee.sa.gov.au/your-council/council-meetings",
    )

    # Every agenda is titled "Notice of [Special] Council Meeting and Agenda
    # <date>". The base class ranks "notice" as a mark of a lesser paper, so
    # on 18 September and 20 November 2024, when the council held an
    # ordinary and a special meeting on the same day, it saw no clean
    # agenda, kept one meeting, and dropped the special meeting's papers.
    # Read without the "Notice of", each agenda names its sitting.
    retitle = (
        (
            re.compile(r"^Notice of ((?:Special )?Council Meeting) and Agenda", re.I),
            r"\1 Agenda",
        ),
    )

    def __init__(self):
        super().__init__(
            "southern_mallee", "SA", "https://www.southernmallee.sa.gov.au"
        )
