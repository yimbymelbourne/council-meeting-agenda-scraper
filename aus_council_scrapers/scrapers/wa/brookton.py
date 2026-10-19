from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import _AGENDA, _AMENDED
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class BrooktonScraper(WheatbeltCouncilConnectScraper):
    """Shire of Brookton—documents on each meeting's own page.

    Council meetings only. A year runs to 20–30 meetings across every type,
    each a request: the Audit, Employment, Local Emergency Management and
    Bushfire Advisory committees and the electors' meeting, none of which
    decides planning matters, as well as Council. Ordinary and Special
    Meetings of Council keep a production year under the ~20 request aim.

    Headings are hand-typed and sometimes disagree with the date field
    ("24 September 2026 - Ordinary Meeting of Council", entered as 17
    September); the base takes the heading's date where the document
    filenames back it.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-meeting-of-council": "Special Meeting of Council",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 24 s
    # (13 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__("brookton", "WA", "https://www.brookton.wa.gov.au")

    def _pick_documents(self, links):
        # The base takes the first amended agenda it meets. Brookton lists
        # revisions oldest first: the 19 February 2026 page has "PUBLIC
        # AGENDA", then "(revised)", then "(updated revised)". So the
        # amended agendas are put in reverse order, each in the slot another
        # held, and the base meets the latest one first. Nothing else moves.
        amended = [
            i
            for i, (_, label, url) in enumerate(links)
            if _AGENDA.search(f"{label} {url}") and _AMENDED.search(f"{label} {url}")
        ]
        reordered = list(links)
        for slot, i in zip(amended, reversed(amended)):
            reordered[slot] = links[i]
        return super()._pick_documents(reordered)
