import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper

_COUNCIL_TYPE = "Ordinary & Special Council Meeting"


@register_scraper
class ToowoombaScraper(ResolveScraper):
    # Toowoomba's meeting pages link the tenant's /web/ portal, and its
    # whole record is on Resolve (from May 2012), so there is no second
    # source.
    tenant = "toowoomba"

    # Council meetings and the Planning and Development Committee. Most
    # development decisions are made at a "Special Meeting of Council (DA)"
    # held between ordinary meetings, which shares the Council type. Left
    # out are the five other standing committees (economic development,
    # environment and community, finance, infrastructure, water and waste),
    # which meet as often as the planning one; each kept meeting costs a
    # request to learn which documents it has.
    meeting_types = re.compile(
        r"^(Ordinary & Special Council Meeting|Planning and Development Committee)$"
    )

    # Where the packet is the wrong document. Measured 20 Oct 2026 by
    # comparing the sizes of the two files at all 211 meetings in range
    # (every one has both) and reading those where the packet is the
    # smaller, or is the minutes file.
    agenda_documents = {
        # 2020 planning committees whose packet is the two-page notice of
        # meeting; the agenda is the three-page order of business.
        819: "agenda",
        811: "agenda",
        805: "agenda",
        # 13 April 2021 planning committee: the packet is the two-page order
        # of business (81 KB); the agenda is the 225-page agenda with the
        # reports (46 MB).
        762: "agenda",
        # 17 May and 19 July 2022 Ordinary meetings: the packet is an empty
        # file.
        703: "agenda",
        705: "agenda",
        # 23 March 2022 special meeting: the packet is the same file as the
        # minutes (the confirmation-of-minutes item from 6 April 2022).
        878: "agenda",
    }

    # Not `include_unpublished`, though it would matter here: the API marks
    # unpublished 20 of the 22 Ordinary meetings from 16 June 2020 to 15
    # March 2022 (all but 21 July 2020 and 18 January 2022), nine special
    # meetings of 2020-2021 (seven of them DA meetings) and the planning
    # committee of 12 April 2022. DocPreview still serves agendas and
    # minutes for the ones sampled. Learning which exist means asking
    # DocPreview, and toowoomba.resolve.red's robots.txt is `Disallow: /`,
    # so those meetings are left out. The scraper requests only
    # api.resolve.red and emits the DocPreview links without fetching them.

    def __init__(self):
        super().__init__("toowoomba", "QLD")

    def _meeting_name(self, event: dict) -> str:
        # Ordinary and special meetings share one type, whose name contains
        # "Special", so the base class cannot tell them apart by type. The
        # free-typed event name does: "Ordinary Meeting of Council - 9
        # December 2025", "Special Meeting of Council (DA) - 29 October
        # 2025", "Post-Election Meeting of Council - 3 April 2024". The
        # "(DA)" marker is kept because those are the meetings that decide
        # development applications, which is what a reader of this data
        # most needs to pick out of the specials.
        if (event.get("meetingTypeName") or "").strip() != _COUNCIL_TYPE:
            return super()._meeting_name(event)
        name = event.get("name") or ""
        if re.search(r"post.election", name, re.IGNORECASE):
            return "Post-Election Meeting of Council"
        if re.search(r"\bspecial\b", name, re.IGNORECASE):
            if re.search(r"\(DA\)", name):
                return "Special Meeting of Council (DA)"
            return "Special Meeting of Council"
        return "Ordinary Meeting of Council"
