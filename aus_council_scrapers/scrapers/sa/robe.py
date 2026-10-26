"""District Council of Robe.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. The council's meetings page
and the Limestone Coast Southern Regional Assessment Panel's, which assesses
development applications for Robe and its neighbours, are read. Each
committee and reference group has a page of its own under
/council/CommitteesandReferenceGroups/, and would cost a listing page and a
20 s crawl delay each.

Robe's council domain answered a plain request for robots.txt with a
Cloudflare challenge even from a home connection (`cf-mitigated:
challenge`, 20 Oct 2026); through Chrome, as the scraper reads it, it is the
standard LGA SA file (see `lgasa`).
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class RobeScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.robe.sa.gov.au/council/councilmeetings",
        "https://www.robe.sa.gov.au/council/CommitteesandReferenceGroups/"
        "limestone-coast-southern-regional-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21-22 s,
    # two Selenium page loads and one 20 s crawl delay between them. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    # Robe files each meeting's confidential items and confidential minutes,
    # once released, beside its public papers ("Council Agenda 8 April 2026 -
    # Confidential Item 19.2", "Confidential Council Minutes 8 March 2023").
    # They are never the meeting's agenda or minutes, and one filed a few
    # days off ("Special Confidential Council Agenda 16 August 2023 - Item
    # 6.1.1", filed under the 19th) became a meeting of its own.
    skip_titles = re.compile(r"confidential", re.IGNORECASE)

    def __init__(self):
        super().__init__("robe", "SA", "https://www.robe.sa.gov.au")
