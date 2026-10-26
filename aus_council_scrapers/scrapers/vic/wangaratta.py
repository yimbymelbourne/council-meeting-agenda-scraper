from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WangarattaScraper(InfoCouncilScraper):
    # The grid holds Council meetings only ("Council" until late 2022,
    # "Scheduled Council" since, and "Special ..." variants), one request a
    # year. The agenda is the _AT or _AT_EMBEDDED paper—agenda with its
    # attachments—which runs from tens of MB up to about 170 MB (168 MB for
    # 25 Jun 2024); the grid offers no lighter agenda-only PDF. An "Addendum Report" row (27 Apr
    # 2021) carries no documents and is skipped by the base class.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "wangaratta",
            "VIC",
            "https://www.wangaratta.vic.gov.au",
            "https://wangaratta.infocouncil.biz/",
        )
