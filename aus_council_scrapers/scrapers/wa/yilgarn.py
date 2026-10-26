from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.yilgarn.wa.gov.au/documents"


@register_scraper
class YilgarnScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Yilgarn—papers in the document library only, labelled by
    month.

    No meetings module (/council-meetings/past 404s). "Agenda <year>" and
    "Minutes <year>" folders from 2021; 2020 and earlier are in "Previous
    Years Agenda/Minutes", which is not read, since nothing in it is dated
    to the day. Labels give the month and no day ("09.2026 - Agenda -
    September 2026 Council Meeting"), and the bracketed date beside them is
    the upload date (11/09 for that agenda, 24/09 for its minutes), not the
    meeting's.

    So the day of an Ordinary meeting comes from the Shire's meeting-dates
    page, which lists the current year's: "Thursday, 17th September 2026"
    and so on. All nine 2026 agendas up on 20 Oct 2026 give the same date
    on their covers as that page. 2025's Ordinary meetings and every
    electors' meeting are corrected below from their covers. Ordinary
    meetings from 2021 to 2024 have no published day anywhere this reads,
    and are left out (about 90 papers); a special meeting is kept where one
    of its papers is dated ("Agenda - Special Meeting of Council 28 July
    2021") or corrected below. One production year is four requests.
    """

    schedule_path = "/shire/shire/meetings.aspx"

    # The 2026 special meetings' papers say "June 2026" and "July 2026",
    # and the May 2024 one's agenda "May 2024"; their covers give the day.
    # Read 20 Oct 2026.
    corrections = {
        # 2025's Ordinary meetings, by their agendas' covers ("Ordinary
        # Meeting of Council Agenda 20 November 2025"); every one agrees with
        # its minutes' cover, and the minutes, labelled by month the same
        # way, join the dated agenda. The July and August minutes open on a
        # copy of the agenda's notice page, but record the votes. Read 20
        # Oct 2026.
        **{
            f"{_DOCUMENTS}/{doc}": {"date": date}
            for doc, date in (
                ("11075/022025-agenda-february-2025-council-meeting", "2025-02-20"),
                ("11088/032025-agenda-march-2025-council-meeting", "2025-03-20"),
                ("11099/042025-agenda-april-2025-council-meeting", "2025-04-17"),
                ("11110/052025-agenda-may-2025-council-meeting", "2025-05-15"),
                ("11125/062025-agenda-june-2025-council-meeting", "2025-06-19"),
                ("11133/072025-agenda-july-2025-council-meeting", "2025-07-17"),
                ("11144/082025-agenda-august-2025-council-meeting", "2025-08-21"),
                ("11153/092025-agenda-september-2025-council-meeting", "2025-09-18"),
                ("11161/102025-agenda-october-2025-council-meeting", "2025-10-16"),
                ("11175/112025-agenda-november-2025-council-meeting", "2025-11-20"),
                ("11186/122025-agenda-december-2025-council-meeting", "2025-12-18"),
            )
        },
        # The electors' meetings, labelled by month, by their covers ("held
        # in the Council Chambers on Tuesday, 9 February 2021"). The
        # February 2024 agenda's first page is headed "Minutes", but the
        # rest is the notice and agenda. Read 20 Oct 2026.
        **{
            f"{_DOCUMENTS}/{doc}": {"date": date}
            for doc, date in (
                ("10598/annual-electors-meeting-agenda-february-2021", "2021-02-09"),
                ("10614/annual-electors-meeting-minutes-february-2021", "2021-02-09"),
                ("10742/annual-electors-meeting-agenda-march-2022", "2022-03-17"),
                ("10749/annual-electors-meeting-minutes-march-2022", "2022-03-17"),
                ("10870/annual-electors-meeting-agenda-april-2023", "2023-04-20"),
                (
                    "10874/april-2023-annual-electors-meeting-minutes-unconfirmed",
                    "2023-04-20",
                ),
                ("10959/agenda-annual-electors-meeting-february-2024", "2024-02-15"),
                ("10964/february-2024-annual-electors-meeting-minutes", "2024-02-15"),
                ("11072/agenda-annual-electors-meeting-february-2025", "2025-02-10"),
                ("11077/minutes-annual-electors-meeting-february-2025", "2025-02-10"),
                ("11176/agenda-annual-electors-meeting-november-2025", "2025-11-20"),
                (
                    "11181/minutes-annual-electors-meeting-november-2025-unconfirmed",
                    "2025-11-20",
                ),
            )
        },
        f"{_DOCUMENTS}/10996/special-meeting-of-council-agend-may-2024": {
            "date": "2024-05-29"
        },
        f"{_DOCUMENTS}/11223/062026-agenda-june-2026-special-council-meeting": {
            "date": "2026-06-02"
        },
        f"{_DOCUMENTS}/11224/062026-minutes-june-2026-special-council-meeting": {
            "date": "2026-06-02"
        },
        f"{_DOCUMENTS}/11245/072026-agenda-july-2026-special-council-meeting": {
            "date": "2026-07-27"
        },
        f"{_DOCUMENTS}/11251/072026-minutes-july-2026-special-council-meeting": {
            "date": "2026-07-27"
        },
    }

    wrong_documents = {
        f"{_DOCUMENTS}/10999/special-meeting-of-council-29-may-2024": (
            "filed under Minutes 2024, but it is the 29 May 2024 special "
            "meeting's agenda again, byte for byte the size of "
            "special-meeting-of-council-agend-may-2024 (read 20 Oct 2026)"
        ),
    }

    def __init__(self):
        super().__init__("yilgarn", "WA", "https://www.yilgarn.wa.gov.au")
