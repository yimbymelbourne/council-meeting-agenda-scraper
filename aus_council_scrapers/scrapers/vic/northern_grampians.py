import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import (
    CheckedDocsPublishedScraper,
    _paper,
)


@register_scraper
class NorthernGrampiansScraper(CheckedDocsPublishedScraper):
    # ngshire.vic.gov.au's Council Meetings page links here ("View upcoming
    # Council meeting agendas and past Minutes"). The list starts on 7
    # September 2020. Once a meeting's minutes are up, its record carries
    # only the minutes—on 20 Oct 2026 no record held an agenda—so agendas
    # appear only while a meeting is upcoming.
    #
    # The list held exactly 100 records on 20 Oct 2026, which looks like a
    # cap. It is probably not: the same endpoint returns 332 for
    # Wollondilly and 271 for Central Coast, and the portal's search, which
    # reaches every document, found nothing older than 7 September 2020.
    publishing_slug = "ngshire"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 43 s, against 8 s run alone.
    expected_seconds = 43

    def __init__(self):
        super().__init__("northern_grampians", "VIC")

    def _meeting_type(self, doc: dict, known_types: list[str]) -> Optional[str]:
        # 15 September and 13 October 2026 are "Unscheduled Council Meeting"
        # in their own minutes but typed "Council Meeting".
        meeting_type = super()._meeting_type(doc, known_types)
        paper = _paper(doc, "Agenda") or _paper(doc, "Minutes") or ""
        if meeting_type == "Council Meeting" and re.search(
            r"\bunscheduled\b", paper, re.I
        ):
            return "Unscheduled Council Meeting"
        return meeting_type
