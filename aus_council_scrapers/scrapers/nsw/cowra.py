import re

from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class CowraScraper(InfoCouncilScraper):
    # The council's Council meetings page sends readers here for agendas and
    # minutes. The grid holds agendas only: no year from 2024 (its first) to
    # 2026 has a single minutes link, and the council site links no other
    # source. Council, Extraordinary Council and General Committee are all
    # kept—the grid is one request a year whatever it lists.
    #
    # Asking for a year the grid does not hold (2020–2023, 2027) returns the
    # current year's grid instead. Those rows are dated in the current year,
    # so the base class's check that each row's date is in the year asked for
    # already drops them.
    tidy_meeting_rows = True

    # Cowra's supplementary agendas are rows named "Council - Late" and
    # "General Committee - Late" (file `..._AT_SUP.PDF`).
    SUPPLEMENTARY_NAME_REGEX = re.compile(
        r"\s*-?\s*\b(?:Supplementary|Late Items|Late)\b", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "cowra",
            "NSW",
            "https://www.cowracouncil.com.au",
            "https://cowra.infocouncil.biz/",
        )
