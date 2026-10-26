import calendar
import datetime
import re

from bs4 import Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.meeting_documents import AGENDA, MINUTES
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.winton.qld.gov.au"
_MEETINGS = f"{_BASE_URL}/Council/Council-Meetings"

# "24.07 Minutes Special Meeting 31 7 2024 JULY signed": a numeric date.
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2}) (\d{1,2}) (20\d{2})(?!\d)")


@register_scraper
class WintonScraper(OpenCitiesContentScraper):
    # Three pages with an accordion per year: business papers (agendas)
    # from 2020, minutes from 2022, and an archive of minutes to 2021.
    # Each label starts with the year and month ("26.07 Business Paper
    # JULY", "26.07 Minutes 27 JULY SPECIAL"), and only special meetings
    # ever give a day, in the label or the file. The ordinary meeting each
    # month gives its day nowhere on these pages, so it is dated from its
    # papers' first page (`pdf_dates`); a meeting neither paper dates is
    # left out, never dated to the 1st. The minutes first: their first
    # bytes give the day ("MINUTES Ordinary Council Meeting Thursday, 16
    # July 2026"), while a business paper's cover is rarely in its first
    # bytes and the file, served without a length, runs past 8 MB. A paper
    # not readable from its first bytes is downloaded whole only up to 2 MB.
    # That misses most meetings of 2020-2025, whose minutes are signed scans
    # with no text; their business papers' covers were read once instead
    # and are listed in `misfiled`. Late papers and correspondence are not
    # the agenda and are left out too.
    #
    # Robots.txt disallows only /MyCity/ and a few unrelated pages, and
    # sets no Crawl-delay. Two page requests a night (the archive only for
    # 2021 and before), plus a PDF read for each month-only meeting of the
    # year.
    pages = [
        ContentPage(f"{_MEETINGS}/Business-Papers"),
        ContentPage(f"{_MEETINGS}/Council-Minutes", holds=lambda y: y >= 2022),
        ContentPage(
            f"{_MEETINGS}/Previous-Agendas-and-Minutes", holds=lambda y: y <= 2021
        ),
    ]
    # Only special meetings give a day, so a year has no meeting until its
    # first one (26 July in 2024, 31 March in 2025, 30 April in 2026).
    # Until then the year raises rather than returning nothing as if it
    # were quiet.
    month_only_fails = True

    pdf_dates = True
    pdf_kinds = (MINUTES, AGENDA)
    pdf_full_limit = 2 * 1024 * 1024
    # 2026: 13 PDF reads, 4.6 MB, 32 s from a home IP (26 Oct 2026).
    expected_seconds = 32.0

    # Month-only business papers whose meetings nothing above dates: the
    # minutes are signed scans with no text, and the business paper, 3-48
    # MB, has its cover past the 2 MB read. Each cover gives the day
    # ("BUSINESS PAPER Ordinary Council Meeting Thursday, 14 December
    # 2023"); read once, 26 Oct 2026. The month's minutes join them. Not
    # listed: July 2023, whose business paper has no text either.
    misfiled = {
        "2001_business_paper___jan.pdf": datetime.date(2020, 1, 23),
        "2002_business_paper___feb.pdf": datetime.date(2020, 2, 20),
        "2003_business_paper___march.pdf": datetime.date(2020, 3, 19),
        "2004_business_paper___april.pdf": datetime.date(2020, 4, 23),
        "2007_special_business_paper___july.pdf": datetime.date(2020, 7, 23),
        "2009_business_paper___sept.pdf": datetime.date(2020, 9, 17),
        "2012_business_paper_december.pdf": datetime.date(2020, 12, 10),
        "2102_business_paper_february_web.pdf": datetime.date(2021, 2, 22),
        "2108_august_business_paper.pdf": datetime.date(2021, 8, 19),
        "2110_business_paper_october_web.pdf": datetime.date(2021, 10, 21),
        "business_paper___web-feb.pdf": datetime.date(2022, 2, 17),
        "2207_business_paper_july.pdf": datetime.date(2022, 7, 25),
        "2209_business_paper___september.pdf": datetime.date(2022, 9, 15),
        "2210_business_paper_october_new.pdf": datetime.date(2022, 10, 24),
        "2211_business_paper_november_web.pdf": datetime.date(2022, 11, 14),
        "2212_business_paper_december_web.pdf": datetime.date(2022, 12, 15),
        "2301_business_paper_january.pdf": datetime.date(2023, 1, 19),
        "2302_business_paper_february_new.pdf": datetime.date(2023, 2, 16),
        "2303_business_paper_march.pdf": datetime.date(2023, 3, 16),
        "2304_business_paper_april.pdf": datetime.date(2023, 4, 20),
        "2305_business_paper_may_web.pdf": datetime.date(2023, 5, 18),
        "2306_business_paper_june.pdf": datetime.date(2023, 6, 15),
        "2308_business_paper_august.pdf": datetime.date(2023, 8, 17),
        "2309_business_paper_september.pdf": datetime.date(2023, 9, 15),
        "2310_business_paper_october.pdf": datetime.date(2023, 10, 13),
        "2311_business_paper_november.pdf": datetime.date(2023, 11, 16),
        "2311_special_council_meeting_november.pdf": datetime.date(2023, 11, 24),
        "2312_business_paper_december.pdf": datetime.date(2023, 12, 14),
        "2401_business_paper_january.pdf": datetime.date(2024, 1, 18),
        "2404_business_paper_april.pdf": datetime.date(2024, 4, 19),
        "2405_business_paper_may.pdf": datetime.date(2024, 5, 16),
        "2407_business_paper_july.pdf": datetime.date(2024, 7, 18),
        "2407_business_paper_special_budget_adoption_meeting_july.pdf": datetime.date(
            2024, 7, 26
        ),
        "2408_business_paper_august.pdf": datetime.date(2024, 8, 15),
        "2409_business_paper_september.pdf": datetime.date(2024, 9, 19),
        "2410_business_paper.pdf": datetime.date(2024, 10, 17),
        "2412_business_paper_december_new1__part1__1_.pdf": datetime.date(2024, 12, 19),
        "2502_business_paper_february.pdf": datetime.date(2025, 2, 20),
        "2511-business-paper-november_part1.pdf": datetime.date(2025, 11, 20),
    }

    def __init__(self):
        super().__init__("winton", "QLD", _BASE_URL)

    def link_label(self, a: Tag, label: str) -> str:
        def numeric(m: re.Match) -> str:
            month = int(m.group(2))
            if not 1 <= month <= 12:
                return m.group(0)
            return f"{m.group(1)} {calendar.month_name[month]} {m.group(3)}"

        # The leading year and month, "25.02" or "2001": in "25.02 February
        # Minutes and Budget" the 02 would read as the 2nd.
        label = re.sub(r"^\s*\d{2}\.?\d{1,2}\b\.*\s*", "", label)
        label = _NUMERIC_DATE.sub(numeric, label)
        # "SPECIAL" and "(signed)" are how the label is typed, not the name.
        label = re.sub(r"\(?\bsigned\b\)?", " ", label, flags=re.IGNORECASE)
        # "Business Paper DECEMBER NEW1 _Part3" and "February Minutes and
        # Budget" name no meeting but the month's ordinary one.
        label = re.sub(
            r"\bNEW\d*\b|(?<![a-z])_?Part\s*\d+\b", " ", label, flags=re.IGNORECASE
        )
        label = re.sub(
            r"\b(Minutes)\s+and\s+Budget\b", r"\1", label, flags=re.IGNORECASE
        )
        label = re.sub(r"\bSPECIAL\b", "Special", label)
        label = re.sub(r"\bSpecial Council Meeting\b", "Special Meeting", label)
        # "25.03 Special Council Meeting 31 MARCH 2025" is filed among the
        # business papers and says nothing else about which paper it is.
        if "/business-papers/" in a.get("href", "") and not re.search(
            r"\b(?:business\s+papers?|agenda|minutes)\b", label, re.IGNORECASE
        ):
            label = f"{label} Business Paper"
        return label
