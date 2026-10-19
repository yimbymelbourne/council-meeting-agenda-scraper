import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import ArchiveListing, ResolveWithLGASAArchive

LISTINGS = (
    "https://www.charlessturt.sa.gov.au/council/council-documents/agendas-and-minutes"
)


@register_scraper
class CharlesSturtScraper(ResolveWithLGASAArchive):
    # One production year (2026), measured 19 Oct 2026 from a home IP: 16 s,
    # of which the panel's listing page through Chrome is one request; the
    # rest is Resolve. Cloudflare's challenge adds 6-9 s on a runner. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 16

    # Charles Sturt's agendas-and-minutes page frames its Resolve portal for
    # meetings from 8 July 2025; the tenant's first event is the 14 July 2025
    # Council meeting. The rest is in the council's LGA SA collection, on
    # two of the per-committee listing pages that page links:
    #
    # - Council meetings before the move, 2018 to 23 June 2025 ("Please
    #   note: All documents below are for meetings prior to 8 July 2025").
    # - The Council Assessment Panel, every year including this one. The
    #   tenant has no panel type, so this listing is read every night.
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
    # —and 20 s apart; see aus_council_scrapers/lgasa.py.
    tenant = "charlessturt"
    resolve_from = datetime.date(2025, 7, 14)

    # Ordinary Council only, the one Council type the tenant has; a special
    # meeting is named from its event. Left out are the audit, corporate
    # services, operations, and strategic and engagement committees; each
    # kept meeting costs a request to learn which documents it has.
    meeting_types = re.compile(r"^Ordinary Council$")
    # Named as the archive names the same meetings, so a Council meeting
    # reads the same either side of the move.
    meeting_type_names = {"Ordinary Council": "Council Meeting"}

    archive_listings = (
        ArchiveListing(f"{LISTINGS}/councilagendas-and-minutes", until=resolve_from),
        ArchiveListing(
            f"{LISTINGS}/cap_agenda_-and-_minutes",
            keep=re.compile(r"Assessment Panel"),
        ),
    )

    def __init__(self):
        super().__init__("charles_sturt", "SA")
