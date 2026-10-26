from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class EsperanceScraper(InfoCouncilScraper):
    # Self-hosted InfoCouncil, framed into the council's agenda-minutes page.
    # The CouncilConnect meetings module on www.esperance.wa.gov.au covers
    # only 2026 and its meeting pages carry no documents, so it is ignored.
    #
    # A year before 2010 answers with the current year's grid rather than an
    # error. That cannot reach the output: EARLIEST_YEAR is later, and the
    # base class drops any row whose date is not in the year it asked for.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "esperance",
            "WA",
            "https://www.esperance.wa.gov.au",
            "https://infocouncil.esperance.wa.gov.au/Infocouncil/",
        )
