import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_library import (
    DEFAULT_NAMES,
    CouncilConnectDocumentLibraryScraper,
)

_DOCUMENTS = "https://www.northampton.wa.gov.au/documents"


@register_scraper
class NorthamptonScraper(CouncilConnectDocumentLibraryScraper):
    """Shire of Northampton—papers in the document library only.

    The past-meetings page sends readers to the library "for all Council
    Meeting documentation prior to September 2026", one "Agendas <year>" and
    one "Minutes <year>" folder a year (2023's is "Agenda 2023"). The
    meetings module the Shire took up in September 2026 lists the Ordinary
    meetings of 20 August to 19 November 2026, but none of their pages has
    a document (checked 20 Oct 2026); those meetings' papers are in the
    library too. If the Shire starts attaching papers in the module, this
    needs reading the module as well. One production year is three
    requests.

    Most labels are the date alone ("21 February 2020"), which is an
    Ordinary meeting. The budget meetings ("Budget Minutes 29 July 2020",
    "1 August 2025 - Budget") are Special Budget Meetings of Council by
    their covers.
    """

    names = (
        *DEFAULT_NAMES,
        (re.compile(r"\bbudget\b", re.IGNORECASE), "Special Council Meeting"),
    )
    extra_name_words = frozenset({"budget"})

    corrections = {
        # "2024 2025 Annual Electors Meeting" (minutes, no date): held at
        # 5:00 pm on 29 January 2026 in the Allen Centre, Kalbarri, by the
        # minutes. Read 20 Oct 2026.
        f"{_DOCUMENTS}/826/2024-2025-annual-electors-meeting": {"date": "2026-01-29"},
        # The agenda calls the June 2020 Ordinary meeting for Friday 19 June;
        # the minutes say it was held on Monday 22 June 2020, and confirm
        # the 15 May meeting's minutes, so it is the same meeting, put back.
        # Read 20 Oct 2026.
        f"{_DOCUMENTS}/456/19-june-2020": {"date": "2020-06-22"},
    }

    def __init__(self):
        super().__init__("northampton", "WA", "https://www.northampton.wa.gov.au")
