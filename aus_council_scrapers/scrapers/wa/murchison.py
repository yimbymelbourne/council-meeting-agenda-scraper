from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.murchison.wa.gov.au/documents"


@register_scraper
class MurchisonScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Murchison—papers in the document library only, labelled by
    month.

    One "Minutes & Agendas <year>" folder a year holds the agendas, minutes,
    attachments, recordings and the audit committee's papers together.
    Apart from April to June 2021, the labels give the month and no day
    ("Agenda OCM February 2025"), and the bracketed date beside them is the
    upload date.

    The current year's Ordinary meetings take their day from the Shire's
    meeting-dates page ("Thursday 23 July 2026"); every 2026 agenda up on
    20 Oct 2026 gives the same date on its cover. 2025's are corrected below
    from their agendas' covers, as are the electors' meetings, which the
    page does not list. Other years' month-only papers are dated from
    their PDFs' first page (`pdf_dates`, agenda first), and left out where
    it gives no day in the label's month. The
    recordings' labels often carry a day but are not used: "OCM Recording
    29 May 2025" is of a meeting held on 22 May. One production year is the
    index, the year's folder and the dates page, three requests.
    """

    schedule_path = "/councilmeeting-dates.aspx"

    # 2025's Ordinary meetings, by their agendas' covers ("To be held ... on
    # Friday 28 February 2025"). Each month's minutes are labelled the same
    # way and join the dated agenda.
    #
    # The electors' meetings, by their agendas' and minutes' covers ("on
    # Friday 27 February 2026, commencing at 1:30pm"). The 2021 and 2023
    # meetings have only a public notice beside the minutes, which is not
    # an agenda and is not read. Read 20 Oct 2026.
    corrections = {
        f"{_DOCUMENTS}/{doc}": {"date": date}
        for doc, date in (
            ("585/annual-electors-meeting-agenda-march-2020", "2020-03-26"),
            ("591/annual-electors-meeting-minutes-march-2020", "2020-03-26"),
            ("687/september-2021-annual-electors-meeting-minutes", "2021-09-23"),
            ("810/annual-meeting-of-electors-minutes-july-2023", "2023-07-27"),
            ("845/annual-meeting-of-electors-agenda-march-2024", "2024-03-28"),
            ("848/annual-meeting-of-electors-minutes-march-2024", "2024-03-28"),
            ("909/annual-electors-meeting-agenda-february-2025", "2025-02-28"),
            ("1010/annual-electors-meeting-agenda-february-2026", "2026-02-27"),
            ("1015/annual-electors-meeting-minutes-february-2026", "2026-02-27"),
            ("907/agenda-ocm-february-2025", "2025-02-28"),
            ("920/agenda-ocm-march-2025", "2025-03-27"),
            ("929/agenda-ocm-april-2025", "2025-04-30"),
            ("935/agenda-ocm-may-2025", "2025-05-22"),
            ("944/agenda-ocm-june-2025", "2025-06-26"),
            ("952/agenda-ocm-july-2025", "2025-07-24"),
            ("962/agenda-ocm-august-2025", "2025-08-28"),
            ("971/agenda-ocm-september-2025", "2025-09-26"),
            ("980/agenda-ocm-october-2025", "2025-10-23"),
            ("987/agenda-ocm-november-2025", "2025-11-27"),
            ("992/agenda-ocm-december-2025", "2025-12-13"),
        )
    }

    pdf_dates = True

    def __init__(self):
        super().__init__("murchison", "WA", "https://www.murchison.wa.gov.au")
