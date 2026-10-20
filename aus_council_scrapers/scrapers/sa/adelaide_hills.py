"""Adelaide Hills Council.

The Craft "meetings module" layout (see `aus_council_scrapers/craft.py`).
The archive never pages: an unbounded query returns every meeting since 2018
on a single 2.5 MB page, and a one-year query about 85 rows. So a production
night is one browser load.

Each meeting can carry three PDFs—Agenda, Minutes and an Order of
Business—each in a folder of its own. Usually the order of business is a
short running sheet beside a separate agenda. But the council sometimes
files the whole agenda there and leaves the agendas folder empty: the
Ordinary Council meetings of 14 November 2023, 9 April 2024 (158 pages),
28 January and 28 October 2025, and the Special Council of 8 July 2026 all
open "NOTICE OF MEETING" from `order-of-business/`. Information or Briefing
Sessions never use the agendas folder at all; their two-page session agenda
("...-IOBS-Agenda.pdf") is always filed as the order of business. So when
the agendas folder holds no agenda, the order-of-business PDF is taken as
the agenda; when it does, the order of business is ignored.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import CraftMeetingsModuleScraper


@register_scraper
class AdelaideHillsScraper(CraftMeetingsModuleScraper):
    listing_url = (
        "https://www.ahc.sa.gov.au/council/council-and-committees/agenda-minutes"
    )
    fallback_agenda_folder = re.compile(r"/order-of-business/", re.IGNORECASE)

    # Measured from a GitHub-hosted runner: plain requests get the AWS WAF
    # challenge whatever the User-Agent, and headless Chrome gets CloudFront's
    # 403 "Request blocked" on the HeadlessChrome token alone. Chrome with the
    # token stripped clears both.
    strip_headless_user_agent = True

    def __init__(self):
        super().__init__("adelaide_hills", "SA", "https://www.ahc.sa.gov.au")
