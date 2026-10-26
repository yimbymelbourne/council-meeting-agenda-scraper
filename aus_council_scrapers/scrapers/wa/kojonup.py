from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)


@register_scraper
class KojonupScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Kojonup—papers in the document library only.

    The site has no meetings module (/council-meetings/past 404s). Each year
    has a "Council Meeting Agendas > <year>" and a "Council Meeting Minutes
    > <year>" folder; the 2026 minutes folder uses the library's list layout
    and every other year its table layout. Special meetings are in the year
    folders. The "Special Council Agendas" folder holds only 2011's papers
    and a copy of the 2 August 2022 agenda that is in the 2022 folder too,
    so it is not read. The electors' meetings have a folder of their own
    with no year, read every run: one production year is the index, two
    year folders and that one, four requests.

    The Regional Development Assessment Panel's agendas and minutes are
    filed with the Council's (3 and 17 September 2026), and are kept.
    """

    undated_folders = ("Annual Electors Meeting",)

    # One production year measured 7.2 s and 9.2 s on 20 Oct 2026: the
    # folders are slow to answer, not many.
    expected_seconds = 8.0

    corrections = {
        # Labelled "Special Council Meeting- 8 August 2026", a Saturday. The
        # agenda's cover calls the meeting for Wednesday 5 August 2026, the
        # date its minutes are filed under. Read 20 Oct 2026.
        "https://www.kojonup.wa.gov.au/documents/1671/06-agenda-special-council-meeting-8-august-2026": {
            "date": "2026-08-05"
        },
    }

    def __init__(self):
        super().__init__("kojonup", "WA", "https://www.kojonup.wa.gov.au")
