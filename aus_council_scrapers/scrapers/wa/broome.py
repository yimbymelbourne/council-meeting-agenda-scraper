import re

from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class BroomeScraper(InfoCouncilScraper):
    # The council site (OpenCities) does not hold the papers; InfoCouncil
    # does, one request a year. Council supplementary agendas get rows of
    # their own, which the tidy flag folds onto the parent meeting.
    tidy_meeting_rows = True

    # The base pattern, plus _DRAFT. The 14 Feb 2023 Audit and Risk
    # Committee has a second row holding only ARC_14022023_AGN_3864_AT_DRAFT,
    # beside the final agenda and minutes. A draft is not the agenda, and
    # left in it becomes a second meeting with the same name and date.
    SUPPLEMENTARY_FILE_REGEX = re.compile(
        r"_(?:SUP|CHAIRMANS|DRAFT)(?:_\w*)?\.(?:PDF|HTML?)$", re.I
    )

    def __init__(self):
        super().__init__(
            "broome",
            "WA",
            "https://www.broome.wa.gov.au",
            "https://broome.infocouncil.biz/",
        )
