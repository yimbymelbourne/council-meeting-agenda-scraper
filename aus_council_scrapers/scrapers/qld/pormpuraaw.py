import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import (
    CheckedDocsPublishedScraper,
    _paper,
)


@register_scraper
class PormpuraawScraper(CheckedDocsPublishedScraper):
    # The council's Council Meeting Information page links here for 2026
    # onward. 2018-2025 are on that WordPress page itself, as toggles of
    # direct PDF links, and are not read yet: production asks only for the
    # current year, and the archive is a separate piece of work.
    #
    # Filenames are not reliable here. The 20 October 2026 agenda is filed as
    # "Ordinary Council Meeting -19 October 2026.pdf", but the notice inside
    # names Tuesday 20 October, the day DocsPublished gives, so dates come
    # from the record, never the filename.
    publishing_slug = "Pormpuraaw"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 34 s, against 5 s run alone.
    expected_seconds = 34

    def __init__(self):
        super().__init__("pormpuraaw", "QLD")

    def _meeting_type(self, doc: dict, known_types: list[str]) -> Optional[str]:
        # Every record is typed "Council Meeting"; the filename says
        # "Special Council Meeting" or "Special Budget Council Meeting".
        meeting_type = super()._meeting_type(doc, known_types)
        paper = _paper(doc, "Agenda") or _paper(doc, "Minutes") or ""
        if meeting_type == "Council Meeting" and re.search(r"\bspecial\b", paper, re.I):
            return "Special Council Meeting"
        return meeting_type
