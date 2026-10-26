import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class BarcaldineScraper(ResolveScraper):
    # Barcaldine moved to Resolve for its 15 October 2025 Ordinary meeting.
    # Its papers from 2016 to September 2025 are direct PDF links on a page
    # per year under https://www.barcaldinerc.qld.gov.au/Our-Council/Council-Meetings
    # (OpenCities content pages); reading them is left to the shared
    # content-page base being built for that shape. Production asks for a
    # year that is all Resolve, so that archive costs it nothing.
    tenant = "barcaldine"
    resolve_from = datetime.date(2025, 10, 15)

    # The tenant's only two types. The budget meeting is an Ordinary Council
    # event named "Special Budget Meeting", which the base class names
    # Special Council from the event name. Naming the types keeps a
    # committee the council starts publishing here from adding a detail
    # call per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^(Ordinary|Special) Council$")

    def __init__(self):
        super().__init__("barcaldine", "QLD")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # The archive years exist on the council's site but are not read
        # yet, so a run asking for them must not pass as a council with no
        # meetings. Raising here fails a run that wants only archive years;
        # one that also wants Resolve years keeps those, and the base class
        # logs this message as a warning.
        unread = sorted(year for year in wanted if 2016 <= year <= 2025)
        if unread:
            raise NotImplementedError(
                f"{self.council_name}: meetings for {unread} are on "
                f"its per-year content pages, which this scraper "
                f"does not read yet"
            )
        return []
