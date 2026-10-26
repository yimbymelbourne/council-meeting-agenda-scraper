import re
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import (
    CheckedDocsPublishedScraper,
    _paper,
)


@register_scraper
class WollondillyScraper(CheckedDocsPublishedScraper):
    # The council's Ordinary Meeting page links here. DocsPublished holds the
    # whole history back to 2015. Its Community Forums—where residents
    # address councillors ahead of a Council meeting—are kept: a "Notice of
    # Community Forum" is the forum's agenda and its "Record of Proceedings"
    # its minutes.
    #
    # In 2019 several forums were entered twice: the notice on the right
    # day, the record of proceedings on a phantom record a month or more
    # away (8 June for 8 July, 12 June for 12 August). The base checks move
    # each record of proceedings to the forum its filename names.
    publishing_slug = "wollondilly"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 48 s, against 9 s run alone.
    expected_seconds = 48

    def __init__(self):
        super().__init__("wollondilly", "NSW")

    def _meeting_type(self, doc: dict, known_types: list[str]) -> Optional[str]:
        # 11 June 2019's forum notice was filed under "Extraordinary Council
        # Meeting", beside a Community Forum record holding that night's
        # record of proceedings. Typing it as the forum lets the two join.
        agenda = _paper(doc, "Agenda") or ""
        if re.match(r"\s*notice of (?:special )?community forum", agenda, re.I):
            return "Community Forum"
        return super()._meeting_type(doc, known_types)
