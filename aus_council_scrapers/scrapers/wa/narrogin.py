from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.narrogin.wa.gov.au/documents"


@register_scraper
class NarroginScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Narrogin—papers in the document library only.

    The site's meetings module is not used (/council-meetings/past 404s).
    Each year has "Agendas > <year> Agenda(s)" and "Minutes > <year>
    Minutes" folders. Minutes are often posted twice, unconfirmed and then
    confirmed, and the confirmed copy is kept. The electors' meetings have
    one folder for every year, read each run. The committees' folders
    ("Committees > ...") are left out, and the "Audio > ..." folders hold
    recordings only. One production year is four requests.
    """

    undated_folders = ("Annual Electors Meetings",)

    # One production year measured 7.9 s and 8.0 s on 20 Oct 2026.
    expected_seconds = 8.0

    corrections = {
        # Labelled "Agenda - 27-7-2020"; the agenda calls the meeting for
        # Tuesday 28 July 2020, the date its minutes are filed under. Read
        # 20 Oct 2026.
        f"{_DOCUMENTS}/929/agenda-27-7-2020": {"date": "2020-07-28"},
        # Labelled 23 March 2023; the agenda and the minutes both say the
        # meeting was on 22 March 2023. Read 20 Oct 2026.
        f"{_DOCUMENTS}/1427/agenda-ordinary-council-meeting-23-march-2023": {
            "date": "2023-03-22"
        },
    }

    def __init__(self):
        super().__init__("narrogin", "WA", "https://www.narrogin.wa.gov.au")
