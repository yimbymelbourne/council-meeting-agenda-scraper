import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper

# Cloncurry once filed a supplementary agenda as an event of its own, typed
# as the Ordinary meeting it adds to: "Ordinary Council Meeting - 2022-12-13
# (Supplementary Agenda)".
_SUPPLEMENTARY = re.compile(r"\bsupplementary\b", re.IGNORECASE)

# The statutory meeting after a general election ("Post-Election Meeting - 9
# April 2024") is filed under the Ordinary type with no "special" in its
# name.
_POST_ELECTION = re.compile(r"\bpost[- ]election\b", re.IGNORECASE)


@register_scraper
class CloncurryScraper(ResolveScraper):
    # Cloncurry's Council-Meetings page links only to its CivicClerk portal
    # (cloncurry.civicclerk.com.au, the same tenant), which runs
    # continuously from January 2021; nothing older is on the website.
    #
    # Seventeen past events from 2021 and 2022 are unpublished. DocPreview
    # still serves their PDFs, but neither the portal nor the /web/ grid
    # lists them, and the tenant host's robots.txt is "Disallow: /", so they
    # are not probed for (include_unpublished stays off).
    tenant = "cloncurry"

    # The tenant's only two types. Naming them keeps a committee the council
    # starts publishing here from adding a detail call per meeting to the
    # nightly run unasked.
    meeting_types = re.compile(r"^(Ordinary|Special) Council Meeting$")

    def __init__(self):
        super().__init__("cloncurry", "QLD")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        # Kept, the supplementary event would be the 13 December 2022
        # Ordinary meeting with the supplementary paper as its agenda. That
        # meeting's own event is unpublished, so it is left out entirely.
        # Checked before the detail call, so it is free.
        if _SUPPLEMENTARY.search(event.get("name") or ""):
            return None
        return super()._record(event, today)

    def _meeting_name(self, event: dict) -> str:
        # Named Special Council Meeting, as Cook (which types its own 9 April
        # 2024 post-election meeting Special) and Balonne ("Special Post
        # Election Meeting") name theirs: it is called outside the ordinary
        # meeting cycle, and naming it Ordinary would make the same kind of
        # meeting read differently from one council to the next.
        if _POST_ELECTION.search(event.get("name") or ""):
            return "Special Council Meeting"
        return super()._meeting_name(event)
