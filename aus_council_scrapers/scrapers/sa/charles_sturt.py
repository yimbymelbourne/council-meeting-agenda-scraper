import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class CharlesSturtScraper(ResolveScraper):
    # Charles Sturt's page says its Resolve portal holds meetings from 8
    # July 2025; the tenant's first event is the 14 July 2025 Council
    # meeting. Everything else is in the LGA SA Funnelback collection
    # charles-sturt-council-minutes-and-agenda-push: Council meetings back to
    # 2013 and the Council Assessment Panel, which was never moved to
    # Resolve, for every year including this one.
    #
    # NOT READ YET. Funnelback and the council's own site answer the
    # GitHub runner with a Cloudflare challenge, which only Selenium with
    # `strip_headless_user_agent` gets past, and that reader is being built
    # on its own branch (build/lgasa-funnelback). Until it is wired into
    # `other_meetings` this council has no panel coverage and no Council
    # meetings before 14 July 2025.
    tenant = "charlessturt"
    resolve_from = datetime.date(2025, 7, 14)

    # Ordinary Council only, the one Council type the tenant has. Left out
    # are the audit, corporate services, operations, and strategic and
    # engagement committees; each kept meeting costs a request to learn
    # which documents it has.
    meeting_types = re.compile(r"^Ordinary Council$")

    def __init__(self):
        super().__init__("charles_sturt", "SA")
