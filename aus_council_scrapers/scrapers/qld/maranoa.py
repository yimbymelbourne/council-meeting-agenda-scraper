import datetime
import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# Maranoa's grid writes dates as 15/10/2026, which the project's DATE_REGEX
# does not match (its numeric form takes hyphens only), so every row would
# come out undated.
NUMERIC_DATE_REGEX = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")


@register_scraper
class MaranoaScraper(InfoCouncilScraper):
    # Almost every Ordinary meeting has a supplementary agenda on a grid row
    # of its own ("Ordinary - Supplementary uploaded 14/10/2026 17:45"),
    # which the tidy flag folds onto the parent meeting.
    tidy_meeting_rows = True

    # The base pattern, plus "Confirmed Minutes". Three meetings (22 Jul
    # 2020, 29 Jul 2020, 13 Jul 2022) have an extra row whose *agenda* cell
    # holds "<prefix>_<date>_Confirmed Minutes_<id>.PDF", beside the row with
    # the real agenda and minutes. Minutes are never the agenda, and left in
    # each would become a second meeting with minutes posing as its agenda.
    SUPPLEMENTARY_FILE_REGEX = re.compile(
        r"(?:_(?:SUP|CHAIRMANS)(?:_\w*)?|_Confirmed Minutes_\d+)\.(?:PDF|HTML?)$",
        re.I,
    )

    def __init__(self):
        super().__init__(
            "maranoa",
            "QLD",
            "https://www.maranoa.qld.gov.au",
            "https://maranoa.infocouncil.biz/",
        )
        self.date_regex = NUMERIC_DATE_REGEX

    def scraper(self) -> list[ScraperReturn]:
        meetings = super().scraper()
        # Rewrite 9/04/2026 as 9 April 2026. Downstream parsing is dateutil
        # without dayfirst, which reads 9/04/2026 as 4 September.
        for meeting in meetings:
            day = datetime.datetime.strptime(meeting.date, "%d/%m/%Y")
            meeting.date = f"{day.day} {day:%B %Y}"
        return meetings
