from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.boyupbrook.wa.gov.au/documents"


@register_scraper
class BoyupBrookScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Boyup Brook—papers in the document library only.

    The meetings module is a calendar with no documents (the 19 December
    2024 Ordinary meeting's page has none, and /council-meetings/past/2025
    404s). The papers are in "Council Agendas > <year> Agendas" and
    "Council Minutes > <year> Minutes", with each meeting's attachments
    beside them as separate files. Until 2021 the agendas folder also holds
    the councillors' briefing agendas ("Public Agenda Briefing"), which are
    left out. One production year is three requests.

    Cloudflare is in front (server: cloudflare, cf-ray), without a challenge
    for the identifying client from home on 20 Oct 2026.
    """

    corrections = {
        # "Special Council Agenda - 7 Agenda 2025": the cover calls the
        # meeting for 7 August 2025, the date its minutes are filed under.
        # Read 20 Oct 2026.
        f"{_DOCUMENTS}/1406/special-council-agenda-7-agenda-2025": {
            "date": "2025-08-07"
        },
        # Two special meetings on 2 March 2023, told apart by the times on
        # their covers: the CEO's appointment called for 3.00 pm (opened at
        # 3.05) and the award of Tender 23/001 at 3.30 pm. Read 20 Oct 2026.
        f"{_DOCUMENTS}/1199/special-council-agenda-2-march-2023-appoint-ceo": {
            "time": "3:00 PM"
        },
        f"{_DOCUMENTS}/1200/special-council-minutes-(appointment-of-ceo)-2-march-2023": {
            "time": "3:00 PM"
        },
        f"{_DOCUMENTS}/1190/special-council-agenda-2-march-2023-tender-23001": {
            "time": "3:30 PM"
        },
        f"{_DOCUMENTS}/1188/special-council-minutes-(tender-23001)-2-march-2023": {
            "time": "3:30 PM"
        },
    }
    wrong_documents = {
        f"{_DOCUMENTS}/1148/agenda-17-november2022": (
            "labelled 17 November 2022, but the cover is the 24 November 2022 "
            "Ordinary meeting's agenda, which is also up as "
            "agenda-24-november-2022 (read 20 Oct 2026)"
        ),
        f"{_DOCUMENTS}/1102/agenda-21-september-2022": (
            "labelled 21 September 2022 and filed under 2021, but the cover is "
            "the 29 September 2022 Ordinary meeting's agenda, which is also up "
            "as agenda-29-september-2022 (read 20 Oct 2026)"
        ),
    }

    def __init__(self):
        super().__init__("boyup_brook", "WA", "https://www.boyupbrook.wa.gov.au")
