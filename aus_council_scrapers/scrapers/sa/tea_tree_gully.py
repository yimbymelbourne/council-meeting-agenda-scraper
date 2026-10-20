import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class TeaTreeGullyScraper(ResolveScraper):
    # Tea Tree Gully publishes Council meetings through Resolve from 22
    # September 2026 (the tenant's 8 September event is there but
    # unpublished). Its page says documents for earlier meetings—Council
    # back to 2022, the Council Assessment Panel, and the 8 September
    # meeting—are in the LGA SA Funnelback collection
    # tea-tree-gully-council-minutes-and-agenda-push.
    #
    # NOT READ YET, so this council's current year starts in late September.
    # Funnelback and the council's own site answer the GitHub runner with a
    # Cloudflare challenge, which only Selenium with
    # `strip_headless_user_agent` gets past, and that reader is being built
    # on its own branch (build/lgasa-funnelback). It belongs in
    # `other_meetings`, for meetings before `resolve_from`.
    tenant = "teatreegully"
    resolve_from = datetime.date(2026, 9, 8)

    # Ordinary and Special Council, and the Council Assessment Panel. Left
    # out are audit and CEO performance review; each kept meeting costs a
    # request to learn which documents it has. Type names carry a trailing
    # space ("Special Meeting of Council "), hence no closing anchor.
    meeting_types = re.compile(
        r"^(Ordinary Council|Special Meeting of Council" r"|Council Assessment Panel)\b"
    )
    meeting_type_names = {
        "Council Assessment Panel (CAP)": "Council Assessment Panel",
    }

    def __init__(self):
        super().__init__("tea_tree_gully", "SA")
