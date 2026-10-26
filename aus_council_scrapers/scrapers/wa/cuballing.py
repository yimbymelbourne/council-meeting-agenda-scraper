from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.cuballing.wa.gov.au/documents"


@register_scraper
class CuballingScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Cuballing—papers in the document library only, often
    labelled by month.

    "<year> Agenda" and "<year> Minutes" folders ("2025 - Agenda" from
    2025). The Ordinary meetings' agendas give the month only ("September
    2026 Ordinary Council Meeting agenda"); since February 2026 their
    minutes give the day ("Minutes - Ordinary Council Meeting 23 September
    2026"), and the agenda joins them. Special and electors' meetings are
    dated to the day. 2025's Ordinary meetings are corrected below from
    their agendas' covers; earlier years' month-only papers are dated from
    their PDFs' first page (`pdf_dates`, agenda first), or corrected below
    where that page is past what `pdf_dates` reads. The minutes folders
    also hold the meetings' recordings, which are not read.

    An agenda is posted a week or so before its minutes, so until then the
    current year's Ordinary meeting takes its day from the Shire's
    meeting-dates page ("21 October 2026"); without it, each new agenda
    would be left out until the meeting was over. The page is not always
    right (it gave 15 April and 15 July 2026; the minutes say both meetings
    were on the 23rd), so its date holds only until the minutes are up,
    and dated minutes win. One production year is the index, the year's two
    folders and the dates page, four requests.
    """

    schedule_path = "/council/council-and-executives/council-meetings.aspx"

    # 2025's Ordinary meetings, by their agendas' covers ("Council Meeting
    # AGENDA To Be Held Wednesday 19th February 2025"). The minutes for each
    # month ("Minutes - February 2025") join the dated agenda. The
    # November recording is labelled the 20th; the agenda says the 19th.
    # Read 20 Oct 2026.
    #
    # The electors' meetings of 2021 and 2022, labelled by month. The 2021
    # agenda's cover says Wednesday 17 February, but it is filed as "March
    # 2021" and the minutes record the meeting as held on Wednesday 17
    # March 2021. Read 20 Oct 2026.
    #
    # Month-only papers of 2020-2024 whose cover is not in the first bytes
    # and whose file is 9-31 MB, past what `pdf_dates` reads: the agenda
    # ("AGENDA for the Ordinary Meeting of Council to be held ...
    # WEDNESDAY 19 JULY 2023"), or the minutes where the agenda has no text
    # or is dated already. The month's other paper joins it. June 2023's
    # meeting was on Friday 30 June. Read 26 Oct 2026.
    corrections = {
        f"{_DOCUMENTS}/{doc}": {"date": date}
        for doc, date in (
            ("4426/agenda-annual-electors-march-2021", "2021-03-17"),
            ("4431/march-2021-annual-electors-meeting", "2021-03-17"),
            ("4472/agenda-annual-electors-meeting-february-2022", "2022-02-16"),
            ("4419/december-2020-minutes", "2020-12-16"),
            ("4499/august-2022-agenda", "2022-08-17"),
            ("4505/minutes-october-2022", "2022-10-19"),
            ("4536/minutes-june-2023", "2023-06-30"),
            ("4535/agenda-july-2023", "2023-07-19"),
            ("4548/agenda-september-2023", "2023-09-20"),
            ("4561/agenda-december-2023", "2023-12-20"),
            ("4573/agenda-may-2024", "2024-05-15"),
            ("4602/february-2025-ordinary-council-meeting-agenda", "2025-02-19"),
            ("4605/march-2025-ordinary-council-meeting-agenda", "2025-03-19"),
            ("4611/april-2025-ordinary-council-meeting-agenda", "2025-04-16"),
            ("4617/may-2025-ordinary-council-meeting-agenda", "2025-05-21"),
            ("4623/june-agenda", "2025-06-18"),
            ("4631/july-2025-ordinary-council-meeting-agenda", "2025-07-16"),
            ("4636/august-2025-ordinary-council-meeting-agenda", "2025-08-20"),
            ("4640/september-2025-ordinary-council-meeting-agenda", "2025-09-17"),
            ("4649/october-2025-ordinary-council-meeting-agenda", "2025-10-22"),
            ("4653/november-2025-ordinary-council-meeting-agenda", "2025-11-19"),
            ("4657/december-2025-ordinary-council-meeting-agenda", "2025-12-17"),
        )
    }

    pdf_dates = True

    def __init__(self):
        super().__init__("cuballing", "WA", "https://www.cuballing.wa.gov.au")
