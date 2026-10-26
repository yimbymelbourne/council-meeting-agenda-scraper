import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper

# York's records-system filenames: "CO_20210427_MIN_3171_AT", where MIN is
# the document class.
_RECORDS_MINUTES = re.compile(r"(?:^|_)min_", re.IGNORECASE)


@register_scraper
class YorkScraper(CouncilConnectScraper):
    """Shire of York—documents on each meeting's own page.

    Council and electors' meetings; the Audit, Risk & Improvement Committee
    is left out. York holds a Special meeting most months (CEO recruitment,
    budget, swearing-in), so Council meetings alone are ~20 a year. The
    all-types listing (three pages) is read and filtered by type, since four
    per-type pages would cost more.

    Each meeting page carries "Agenda & Appendices", often a "LATE Agenda &
    Appendices" and an "Addendum", and since 2026 an "Agenda Briefing
    Record" from the councillors' briefing a week before. The late papers,
    addenda and briefing record are never taken as the agenda.

    The 27 April 2021 meeting's only minutes are "CO_20210427_MIN_3171_AT -
    Confirmed Signed" under "Downloads", with no "minutes" in the label;
    page 1 reads "CONFIRMED MINUTES Ordinary Council Meeting Tuesday, 27
    April 2021". A records-system "_MIN_" filename is read as minutes.
    """

    meeting_types = {
        "ordinary-meeting-of-council": "Ordinary Council Meeting",
        "special-meeting-of-council": "Special Council Meeting",
        "annual-electors-meeting": "Annual Electors Meeting",
        "special-electors-meeting": "Special Electors Meeting",
    }
    type_listings = False
    first_year = 2007
    plausible_times_only = True
    # "Annual Electors Meeting" since 2023, "Annual General Meeting of
    # Electors" before.
    canonical_names = ELECTORS_NAMES

    # One production year, measured 20 Oct 2026 from a home IP: 39 s (20
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 39

    def __init__(self):
        super().__init__("york", "WA", "https://www.york.wa.gov.au")

    def _pick_documents(self, links, meeting_name=None, date=None):
        relabelled = []
        for group, label, url in links:
            filename = url.rsplit("/", 1)[-1]
            if _RECORDS_MINUTES.search(filename) and not re.search(
                r"minut", label, re.IGNORECASE
            ):
                label = f"{label} Minutes"
            relabelled.append((group, label, url))
        return super()._pick_documents(relabelled, meeting_name, date)
