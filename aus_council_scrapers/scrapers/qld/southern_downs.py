import re

from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class SouthernDownsScraper(InfoCouncilScraper):
    # Most 2020–2024 Council meetings have a supplementary agenda on a grid
    # row of its own ("Council Supplementary uploaded 27/03/2025 10:38"—the
    # stamp is a 2025 bulk re-upload, not the meeting), which the tidy flag
    # folds onto the parent meeting.
    tidy_meeting_rows = True

    # The base pattern, plus _DRAFT. The 17 Aug 2020 Sustainable Development
    # committee has two rows: the final agenda with its minutes, and a stale
    # AGN_481_AT_DRAFT.PDF on a row of its own. A draft is not the agenda,
    # and left in it becomes a second meeting with the same name and date.
    SUPPLEMENTARY_FILE_REGEX = re.compile(
        r"_(?:SUP|CHAIRMANS|DRAFT)(?:_\w*)?\.(?:PDF|HTML?)$", re.I
    )

    def __init__(self):
        super().__init__(
            "southern_downs",
            "QLD",
            "https://www.sdrc.qld.gov.au",
            "https://southerndowns.infocouncil.biz/",
        )
