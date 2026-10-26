from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)

_BASE_URL = "https://www.whitsundayrc.qld.gov.au"


@register_scraper
class WhitsundayScraper(OpenCitiesContentScraper):
    # One page with a "Council Meeting Agendas" and a "Council Meeting
    # Minutes" accordion per year from 2020; older papers are by request
    # only, the page says. Labels lead with the date ("23 September 2026 -
    # Unconfirmed Ordinary Council Meeting Minutes"). The 2026 special budget
    # meetings have only a "Notice of Special Meeting - Budget" beside their
    # minutes, which is not the agenda, so those meetings carry minutes alone.
    pages = [
        ContentPage(
            f"{_BASE_URL}/Our-Council/About-Council/Council-Meetings-and-Agendas"
        )
    ]

    misfiled = {
        # "22 April 2020 - Ordinary Council Meeting Agenda" is a second copy
        # of the post-election meeting's notice and agenda ("Notice is hereby
        # given that the Post-election Meeting ... Wednesday 22 April 2020"),
        # listed beside "22 April - Post-Election Meeting Agenda". There was
        # no ordinary meeting that day.
        "22-april-2020-ordinary-council-meeting-agenda.pdf": None,
    }

    def __init__(self):
        super().__init__("whitsunday", "QLD", _BASE_URL)
