import datetime
import re
from urllib.parse import urlparse

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.boulia.qld.gov.au"


@register_scraper
class BouliaScraper(OpenCitiesContentScraper):
    # One page, every year from 2019, with no accordions: an h2 per year
    # ("2026 Meeting Agendas & Minutes") over a "Meeting Agendas" and a
    # "Meeting Minutes" heading (strong, h3 or h6 depending on the year).
    # The 2026 agendas are titled only by the meeting ("23rd January 2026
    # Ordinary Council Meeting"), so the filename or heading gives the kind.
    # Beside them are tabled reports, late reports, councillors'
    # declarations of interest and notices of meeting, none of which is a
    # paper of the meeting.
    #
    # 2023 and early 2024 titles give the month only ("February 2024
    # Ordinary Council Meeting Agenda"); those take the day of the same
    # meeting's minutes where they have one. 2023's minutes are month-only
    # too, so 2023 (and 2020-2022, month-only throughout) is dated from the
    # papers' first page (`pdf_dates`). The budget meetings' papers carry
    # no date at all ("2026-2027 Budget Meeting of Council"), and neither
    # does the 2024 post-election agenda; those from 2024 on are dated from
    # their PDFs in `misfiled`.
    pages = [ContentPage(f"{_BASE_URL}/Council/Council-Meetings")]
    page_headings = ("h2", "h3", "h6", "strong")
    # Filed under "Meeting Minutes" and titled by the meeting ("24th April
    # 2024 Ordinary Meeting Minutes - declaration of interests"), so only
    # the words say they are not the minutes.
    not_the_paper = re.compile(
        r"\bdeclarations?\b|\bdec\.?\s+of\s+int|\btabled\b|\bfinance\s+report",
        re.IGNORECASE,
    )

    misfiled = {
        # Cover: "2026-2027 Budget Meeting Tuesday 30 June 2026"; the
        # minutes: "held on Tuesday 30 June 2026".
        "6.-budget-agenda-2026-2027-budget-meeting-of-council.pdf": datetime.date(
            2026, 6, 30
        ),
        "f.confirmed-2026-2027-budget-meeting.pdf": datetime.date(2026, 6, 30),
        # Cover: "2024/2025 Budget Friday 28 June 2024"; the minutes: "held
        # on Friday 28 June 2024".
        "2024-2025-budget-meeting-agenda.pdf": datetime.date(2024, 6, 28),
        "2024-2025-budget-meeting-minutes.pdf": datetime.date(2024, 6, 28),
        # "Post Election Council Meeting Agenda"; the PDF: "Post Election
        # Meeting Thursday 28 March 2024".
        "post-election-council-meeting-agenda.pdf": datetime.date(2024, 3, 28),
    }

    pdf_dates = True

    def __init__(self):
        super().__init__("boulia", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # The next meeting is listed by its notice before the agenda is
        # out: "23rd October 2026 Ordinary Council Meeting" is
        # "notice-of-ordinary-meeting-23-october-2026.pdf". Say so, and the
        # base leaves it out as a notice.
        filename = urlparse(a.get("href", "")).path.rsplit("/", 1)[-1]
        if re.match(r"notice", filename, re.IGNORECASE):
            label += " - Notice"
        # One name per meeting, whichever paper names the record: the agendas
        # say "Budget Meeting of Council" and "Post Election Council
        # Meeting", the minutes "Budget Meeting" and "Post Election Meeting".
        label = re.sub(r"\bBudget Meeting of Council\b", "Budget Meeting", label)
        return re.sub(r"\bPost Election Council Meeting\b", "Post Election Meeting", label)
