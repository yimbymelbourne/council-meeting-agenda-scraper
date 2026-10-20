import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class MountBarkerScraper(ResolveScraper):
    # Mount Barker moved to Resolve from 1 July 2026. Council and Council
    # Assessment Panel meetings up to June 2026, back to 2016, are in the
    # LGA SA Funnelback collection mount-barker-council-minutes-and-agenda-push.
    #
    # NOT READ YET, so this council's current year starts in July.
    # Funnelback and the council's own site answer the GitHub runner with a
    # Cloudflare challenge, which only Selenium with
    # `strip_headless_user_agent` gets past, and that reader is being built
    # on its own branch (build/lgasa-funnelback). It belongs in
    # `other_meetings`, for meetings before `resolve_from`.
    tenant = "mountbarker"
    resolve_from = datetime.date(2026, 7, 1)

    # Council and the Council Assessment Panel. Left out are audit and the
    # community funding assessment committee; each kept meeting costs a
    # request to learn which documents it has.
    meeting_types = re.compile(r"^(Council Meeting|Council Assessment Panel)\b")
    meeting_type_names = {
        "Council Assessment Panel (CAP)": "Council Assessment Panel",
    }

    def __init__(self):
        super().__init__("mount_barker", "SA")
