import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import ArchiveListing, ResolveWithLGASAArchive

MEETINGS = "https://www.teatreegully.sa.gov.au/council/council-and-committee-meetings"


@register_scraper
class TeaTreeGullyScraper(ResolveWithLGASAArchive):
    # One production year (2026), measured 19 Oct 2026 from a home IP: 24 s,
    # most of it the two listing pages through Chrome, 20 s apart. From 2027
    # neither is read. Cloudflare's challenge adds 6-9 s on a runner. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 24

    # Tea Tree Gully publishes Council meetings through Resolve from 22
    # September 2026; its page says "Documents for Council meetings prior to
    # 22 September 2026 can be found below", and the tenant's 8 September
    # event is there but unpublished. The Council Assessment Panel follows on
    # 28 October 2026, the tenant's first panel event. Everything before
    # those dates is in the council's LGA SA collection, on the Council
    # meetings page (2022 onward) and the panel's own page.
    #
    # The listing pages are read as robots.txt allows (checked 19 Oct 2026,
    # the Matrix default on every LGA SA host): bare paths with only
    # `num_ranks` and `start_rank` added, never what these lines forbid—
    #
    #     Crawl-delay: 20
    #     Disallow: /search
    #     Disallow: *?*query=
    #     Disallow: *?*f.*%7C*=
    #
    # —and 20 s apart; see aus_council_scrapers/lgasa.py. From 2027 neither
    # listing is in range, and a production run reads Resolve alone.
    tenant = "teatreegully"
    resolve_from = datetime.date(2026, 9, 22)

    # Ordinary and Special Council, and the Council Assessment Panel. Left
    # out are audit and CEO performance review; each kept meeting costs a
    # request to learn which documents it has. Type names carry a trailing
    # space ("Special Meeting of Council "), hence no closing anchor.
    meeting_types = re.compile(
        r"^(Ordinary Council|Special Meeting of Council" r"|Council Assessment Panel)\b"
    )
    # Named as the archive names the same bodies, so a meeting type reads the
    # same either side of the move.
    meeting_type_names = {
        "Ordinary Council": "Council Meeting",
        "Special Meeting of Council": "Special Council Meeting",
        "Council Assessment Panel (CAP)": "Council Assessment Panel",
    }

    archive_listings = (
        ArchiveListing(f"{MEETINGS}/council-meeting", until=resolve_from),
        ArchiveListing(
            f"{MEETINGS}/council-assessment-panel",
            until=datetime.date(2026, 10, 28),
            keep=re.compile(r"Assessment Panel"),
        ),
    )

    def __init__(self):
        super().__init__("tea_tree_gully", "SA")
