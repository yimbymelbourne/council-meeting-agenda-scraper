from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    _merge_split_meetings,
    register_scraper,
)

# Two late-2020 Ordinary Council agendas that the grid files under the wrong
# row, keyed by the agenda file name, with the name and date the PDF's own
# cover gives. Each has its minutes on a separate row, so as filed neither
# meeting has both papers on one record.
#
# - OC_04122020_AGN.PDF sits on a row dated 4 Dec 2020, but its cover reads
#   "ORDINARY MEETING AGENDA 8 DECEMBER 2020", and the minutes row
#   (OC_08122020_MIN.PDF) is 8 Dec 2020. The filename stamp is wrong too, so
#   it is no evidence for 4 Dec.
# - EM_24112020_AGN.PDF sits on an "Extraordinary Meeting" row, but its cover
#   reads "ORDINARY MEETING AGENDA 24 NOVEMBER 2020" and its contents match
#   the Ordinary Council minutes of that day (OC_24112020_MIN.PDF) item for
#   item. There was no separate extraordinary meeting.
_MISFILED_AGENDAS = {
    "OC_04122020_AGN.PDF": ("Ordinary Council", "8 Dec 2020"),
    "EM_24112020_AGN.PDF": ("Ordinary Council", "24 Nov 2020"),
}


@register_scraper
class MaitlandScraper(InfoCouncilScraper):
    # Almost every row is an Ordinary Council meeting. Since 2024 the
    # committee cell carries the Town Hall venue after the meeting type, and
    # supplementary agendas get rows of their own ("Ordinary Council
    # Supplementary", filed as _AGN_AT_SUP), so the tidy flag is on: the venue
    # goes to `location` and the supplementary rows fold away.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "maitland",
            "NSW",
            "https://www.maitland.nsw.gov.au",
            "https://maitland.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        corrected = False
        for meeting in results:
            agenda_file = (meeting.agenda_url or "").rsplit("/", 1)[-1]
            if agenda_file in _MISFILED_AGENDAS:
                meeting.name, meeting.date = _MISFILED_AGENDAS[agenda_file]
                meeting._cleaned_date = None
                corrected = True
        # Re-run the base class's merge now the agenda rows carry their
        # meeting's real name and date, so each joins its minutes row.
        return _merge_split_meetings(results) if corrected else results
