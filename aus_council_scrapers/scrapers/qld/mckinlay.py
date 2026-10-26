import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.meeting_documents import AGENDA, MINUTES
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.mckinlay.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/About-Council/Council-meetings"


@register_scraper
class McKinlayScraper(OpenCitiesContentScraper):
    # Two pages with an accordion per year from 2017: agendas ("January
    # 2026 Ordinary Meeting Agenda", "3 March 2026 Special Meeting
    # Agenda") and minutes, labelled by the month alone ("January 2026",
    # "January" under 2025) or the day of a special meeting ("3 March -
    # Special Meeting 2026"). Special meetings mostly give their day;
    # ordinary meetings mostly do not, in the label or the file, and are
    # dated from their papers' first page (`pdf_dates`), or left out where
    # neither gives a day in the month, never dated to the 1st. The minutes
    # first: their first bytes give the day ("CONFIRMED MINUTES OF THE
    # ORDINARY MEETING OF COUNCIL HELD AT ... 15th July 2025"), while an
    # agenda's cover is rarely in its first bytes and the file is 3-11 MB.
    # A paper not readable from its first bytes is downloaded whole only up
    # to 2 MB: agendas first, at the default 8 MB, cost 32 MB a night. The
    # filenames start with the month's place in the year ("05-may-
    # confirmed-ordinary-meeting-minutes.pdf", "10-october-...",
    # "03march2026-..."), which is not the day (`numbered_files`).
    #
    # Robots.txt disallows only /MyCity/ and one old page, and sets no
    # Crawl-delay. Two page requests a night, plus a PDF read for each
    # month-only meeting of the year.
    pages = [
        ContentPage(f"{_MEETINGS}/Meeting-Agendas"),
        ContentPage(f"{_MEETINGS}/Meeting-minutes"),
    ]
    numbered_files = True
    # Only special meetings mostly give a day, so a year has no meeting
    # until its first one (2 April in 2024, 3 March in 2026). Until then
    # the year raises rather than returning nothing as if it were quiet.
    month_only_fails = True

    pdf_dates = True
    pdf_kinds = (MINUTES, AGENDA)
    pdf_full_limit = 2 * 1024 * 1024
    # 2026: 15 PDF reads, 4.2 MB, 32 s from a home IP (26 Oct 2026).
    expected_seconds = 32.0

    def __init__(self):
        super().__init__("mckinlay", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        # The minutes are labelled only by the meeting: "January 2026",
        # "May - Special Meeting", "April 2nd". The accordion says they are
        # minutes.
        if not re.search(r"\b(?:agenda|minutes?)\b", label, re.IGNORECASE):
            label = f"{label} Minutes"
        # "Ordinary Council Meeting" (2018-2021) and "Ordinary Meeting"
        # (2022-) are one body, and so are the special meetings.
        label = re.sub(
            r"\b(Ordinary|Special|Post[\s-]*Election) Council Meeting\b",
            r"\1 Meeting",
            label,
            flags=re.IGNORECASE,
        )
        if not re.search(
            r"\b(?:special|post[\s-]*election|ordinary)\b", label, re.IGNORECASE
        ):
            # The monthly meeting, unnamed: "October 2020 Council Meeting
            # Agenda", or minutes labelled "January".
            if re.search(r"\bCouncil Meeting\b", label, re.IGNORECASE):
                label = re.sub(
                    r"\bCouncil Meeting\b", "Ordinary Meeting", label, flags=re.I
                )
            else:
                label = f"Ordinary Meeting - {label}"
        return label
