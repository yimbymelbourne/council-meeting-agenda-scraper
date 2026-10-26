"""District Council of Cleve.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`, and
`TitleRulesLGASAScraper` for the title rules. There is no page over the
whole collection: /council/agendasminutes ("Council and Committees") is a
landing page, and each body has a page of its own. The council's page and
the Eyre Peninsula Regional Assessment Panel's, which assesses development
applications for Cleve and its neighbours, are read; the audit committee,
the Arno Bay boat ramp committee and the tourism group would cost a listing
page and a 20 s crawl delay each.

Cleve's council domain answered a plain request for robots.txt with a
Cloudflare challenge even from a home connection (`cf-mitigated:
challenge`, 20 Oct 2026); through Chrome, as the scraper reads it, it is the
standard LGA SA file (see `lgasa`).
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa_titles import TitleRulesLGASAScraper


@register_scraper
class CleveScraper(TitleRulesLGASAScraper):
    listing_urls = (
        "https://www.cleve.sa.gov.au/council/agendasminutes/full-council",
        "https://www.cleve.sa.gov.au/council/agendasminutes/"
        "eyre-peninsula-regional-assessment-panel",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 21-22 s,
    # two Selenium page loads and one 20 s crawl delay between them. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 22

    # Filed under "Council" but never a meeting's agenda or minutes:
    # - "Confidential Minutes Released - 17 January 2023": the confidential
    #   part only, released later and sometimes filed a day off, where it
    #   became a minutes-only meeting of its own (16 January 2023).
    # - "Notice of Adjournment of Council Meeting": the 17 June 2025 meeting
    #   was adjourned to the 24th, and the notice is not either one's agenda.
    # - informal gatherings and briefing sessions under s 90A of the Local
    #   Government Act 1999 (SA), at which no decision may be made.
    # - single agenda items uploaded on their own in 2020, numbered by item
    #   ("21.1. DC of Cleve Safety Committee Meeting Minutes", "22.1. Arno
    #   Bay Boat Ramp Committee AGM Meeting Minutes"), which had become the
    #   council's minutes and turned 11 February 2020 into an AGM. The
    #   agenda itself is numbered by its place in the upload ("1. Council
    #   Agenda - 14 January 2020"), with no item number after it.
    skip_titles = re.compile(
        r"confidential|notice of adjourn|items register|informal gathering|"
        r"briefing|^\d+\.\d+",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__("cleve", "SA", "https://www.cleve.sa.gov.au")
