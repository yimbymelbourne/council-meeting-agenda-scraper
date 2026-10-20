import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import (
    CheckedDocsPublishedScraper,
    _paper,
)


@register_scraper
class GrooteArchipelagoScraper(CheckedDocsPublishedScraper):
    # groote.nt.gov.au/agenda-and-minutes links here. The list starts in April
    # 2025. The council's own /agenda-and-minutes and /council-meetings pages
    # link no PDFs, so nothing older was found.
    publishing_slug = "GrooteArchipelagoRegionalCouncil"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 35 s, against 6 s run alone.
    expected_seconds = 35

    def __init__(self):
        super().__init__("groote_archipelago", "NT")

    def _meeting_type(self, doc: dict, known_types: list[str]) -> Optional[str]:
        # The council types three Local Authorities alike, and ordinary and
        # special Council meetings alike. The filename tells them apart:
        # "Angurugu Local Authority - 2 June 2026", "Special Meeting of
        # Council Open - 5 May 2026".
        meeting_type = super()._meeting_type(doc, known_types)
        paper = _paper(doc, "Agenda") or _paper(doc, "Minutes") or ""
        if meeting_type == "Local Authority":
            place = re.match(r"\s*([A-Z][a-z]+) Local Authority\b", paper)
            if place:
                return f"{place.group(1)} Local Authority"
        if meeting_type == "Council Meeting" and re.search(r"\bspecial\b", paper, re.I):
            return "Special Council Meeting"
        return meeting_type
