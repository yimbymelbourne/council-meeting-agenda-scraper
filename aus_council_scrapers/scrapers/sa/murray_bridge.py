"""Rural City of Murray Bridge.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The council
has no page over its whole collection: each committee page lists that
committee only. Three are read: the council's, the Council Assessment
Panel's and the Strategic Planning and Development Policy Committee's—the
council's decisions, its development assessment body and its planning
policy body. Each page is another Selenium request, 20 s after the last
(the crawl delay), so a production year is about 45 s. The Audit and Risk
and Community Advisory committees and the informal gatherings each have a
page of their own too, and are not read: each would add another 20 s.

Any of the three pages failing fails the run, since each is the only source
for its body (see `RelabellingLGASAScraper`).

Council meetings are filed under "Full Council Meeting Agenda & Minutes",
which strips to "Full Council Meeting", not a label the base class reads as
the council by itself.

The 12 March 2024 agenda was published in four files titled "PART A" to
"PART D", with Part A filed under 14 March. The lettered later parts are
dropped so the agenda is Part A, which `_rejoin_misdated` then puts back on
12 March by its title (see `RelabellingLGASAScraper`).
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class MurrayBridgeScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.murraybridge.sa.gov.au/council/council-and-elected-members/"
        "council-meetings/fullcouncilmeeting",
        "https://www.murraybridge.sa.gov.au/council/council-and-elected-members/"
        "council-meetings/dap",
        "https://www.murraybridge.sa.gov.au/council/council-and-elected-members/"
        "council-meetings/strategic-planning-and-development-policy-committee",
    )

    committee_names = {"Full Council Meeting Agenda & Minutes": COUNCIL_MEETING}

    # Case-sensitive on purpose: "PART B", not "part 2 of the budget".
    exclude_titles = re.compile(r"\bPART [B-Z]\b")

    # One production year, measured 20 Oct 2026 from a home IP: 41 s
    # (3 Selenium page loads, two 20 s crawl delays between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 41

    def __init__(self):
        super().__init__("murray_bridge", "SA", "https://www.murraybridge.sa.gov.au")
