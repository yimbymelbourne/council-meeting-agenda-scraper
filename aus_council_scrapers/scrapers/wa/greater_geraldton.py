import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper

# Meeting pages list each report and attachment under a vague "Document"
# heading, labelled with its item code: "CS020-Attachment-Draft-Council-
# Policy", "RR46C-Report-WALGA-State-Council-Agenda-1-March-2023". The last
# names an agenda, and the base would take it over the meeting's own agenda
# (28 February 2023), whose label does not say "agenda". An item code means a
# report or attachment, never the meeting's agenda or minutes.
_ITEM_CODE = re.compile(r"^\s*[A-Z]{2,4}\d+[A-Z]?\s*-")


@register_scraper
class GreaterGeraldtonScraper(TidyCouncilConnectScraper):
    """City of Greater Geraldton—documents on each meeting's own page.

    Every meeting type is read, through the one all-types listing a year:
    the meetings module holds only Council meetings (Ordinary, Special and
    the Annual Meeting of Electors), so there is nothing to filter out. The
    committees' papers are on a separate committee-book page outside the
    module, which this does not read.

    The /past index lists 2011 onward; EARLIEST_YEAR bounds the fetch.
    """

    # Headings are hand-typed and vary; the type names do not.
    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 25 s (13
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("greater_geraldton", "WA", "https://www.cgg.wa.gov.au")

    def _pick_documents(self, links):
        return super()._pick_documents(
            [
                (group, label, url)
                for group, label, url in links
                if not _ITEM_CODE.match(label)
            ]
        )
