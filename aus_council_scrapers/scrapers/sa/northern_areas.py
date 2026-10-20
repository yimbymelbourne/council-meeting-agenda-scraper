"""Northern Areas Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The listing
is the council's own: everything on it is filed under "Agenda and Minutes",
which the base class reads as the council itself, and special meetings are
told apart by their titles ("Minutes - 6 October 2026 (Special Meeting)").
"""

import datetime
from typing import Optional

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import LGASAFunnelbackScraper, _title_date

# How far a title's date may be from the filed date and still replace it.
# Titles state the meeting date, and the filed date is sometimes the upload
# day instead. The 17 October 2023 minutes were filed on the 20th, while the
# confidential minutes released later ("Released Minutes - 17 October 2023")
# were filed on the 17th and stood in for them. Read by the title, both sit
# on the 17th and the full minutes win. The listing's mismatches are 1 to 3
# days; a week stays short of the next meeting.
_TITLE_DAY_WINDOW = 7


@register_scraper
class NorthernAreasScraper(LGASAFunnelbackScraper):
    # Information and briefing sessions have a page of their own
    # (/council/council-meetings/informationbriefing-sessions), not read:
    # they are informal gatherings, not meetings of the council.
    listing_urls = (
        "https://www.nacouncil.sa.gov.au/council/council-meetings/agenda-and-minutes",
    )

    def __init__(self):
        super().__init__("northern_areas", "SA", "https://www.nacouncil.sa.gov.au")

    def _meeting_date(self, filed: str, title: str, year: int) -> Optional[str]:
        stated = _title_date(title)
        if stated is not None:
            filed_day = datetime.date.fromisoformat(filed)
            if (
                stated.year == filed_day.year
                and 0 < abs((stated - filed_day).days) <= _TITLE_DAY_WINDOW
            ):
                return stated.isoformat()
        return super()._meeting_date(filed, title, year)
