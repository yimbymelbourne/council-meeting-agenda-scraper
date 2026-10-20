import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import ArchiveListing, ResolveWithLGASAArchive


@register_scraper
class MountBarkerScraper(ResolveWithLGASAArchive):
    # One production year (2026), measured 19 Oct 2026 from a home IP: 10 s
    # alone, including the Council listing page through Chrome, which is not
    # read from 2027; 17-18 s in full 135-council runs, queued with the other
    # tenants on api.resolve.red. Cloudflare's challenge adds 6-9 s on a
    # runner. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 17

    # Mount Barker moved Council and its assessment panel to Resolve from 1
    # July 2026. Council meetings before that, back to 2016, are in the
    # council's LGA SA collection on its Council Meetings page, read for the
    # years up to 2026; from 2027 a production run reads Resolve alone.
    #
    # That page is read as robots.txt allows (checked 19 Oct 2026, the
    # Matrix default on every LGA SA host): a bare path with only
    # `num_ranks` and `start_rank` added, never what these lines forbid—
    #
    #     Crawl-delay: 20
    #     Disallow: /search
    #     Disallow: *?*query=
    #     Disallow: *?*f.*%7C*=
    #
    # —and 20 s apart; see aus_council_scrapers/lgasa.py.
    #
    # NOT READ: the panel's meetings before September 2026. They are not in
    # the LGA SA collection but in a Content Manager (HPRM) list on the
    # panel's page, 2025 and 2026 only, whose documents are served only from
    # the council's Cloudflare-fronted domain (`/hprm/...?RecordNumber=`);
    # the Matrix origin that serves every other LGA SA document answers 404
    # for them.
    tenant = "mountbarker"
    resolve_from = datetime.date(2026, 7, 1)

    # Council and the Council Assessment Panel. Left out are audit and the
    # community funding assessment committee; each kept meeting costs a
    # request to learn which documents it has.
    meeting_types = re.compile(r"^(Council Meeting|Council Assessment Panel)\b")
    meeting_type_names = {
        "Council Assessment Panel (CAP)": "Council Assessment Panel",
    }

    archive_listings = (
        ArchiveListing(
            "https://www.mountbarker.sa.gov.au/council/meetings/full-council",
            until=resolve_from,
        ),
    )

    def __init__(self):
        super().__init__("mount_barker", "SA")
