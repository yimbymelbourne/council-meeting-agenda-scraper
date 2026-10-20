"""Renmark Paringa Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The
agendas-and-minutes page is only an index: each committee has a page of its
own. Council meetings ("Council (General Council)") and the Riverland
Regional Assessment Panel are read; the panel decides development
applications for Renmark Paringa, Berri Barmera and Loxton Waikerie, and
each of them republishes its papers. The Asset, Audit and Risk, Grants and
Policy committees are not read: each page costs a Selenium load and a 20 s
crawl delay.

Briefing sessions and informal gatherings of council are filed under the
council's label and titled "Agenda - Briefing Session of Council - ...", so
they are dropped by title; see `RegionalLGASAScraper`. Released
confidential papers are kept: several special meetings' only agenda and
minutes are the re-released whole documents ("Minutes - Special Council
Meeting - 12 August 2025 - Confidential section released 5/12/25").
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.lgasa_regional import INFORMAL_TITLES, RegionalLGASAScraper

RRAP = "Riverland Regional Assessment Panel"


@register_scraper
class RenmarkParingaScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.renmarkparinga.sa.gov.au/council/meetings-committees/"
        "agendasandminutes/council-general-council",
        "https://www.renmarkparinga.sa.gov.au/council/meetings-committees/"
        "agendasandminutes/riverland-regional-development-assessment-panel-dap",
    )

    committee_names = {
        "Council (General Council)": COUNCIL_MEETING,
        # Both spellings are in the collection, one missing its "(".
        "Riverland Regional Assessment Panel (RRAP)": RRAP,
        "Riverland Regional Assessment Panel RRAP)": RRAP,
    }

    skip_titles = INFORMAL_TITLES

    # One production year, measured 20 Oct 2026 from a home IP: 21 s (2
    # Selenium page loads and one 20 s crawl delay between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 21

    def __init__(self):
        super().__init__(
            "renmark_paringa", "SA", "https://www.renmarkparinga.sa.gov.au"
        )
