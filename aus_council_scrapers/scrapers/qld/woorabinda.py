import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class WoorabindaScraper(ResolveScraper):
    # Woorabinda's record on Resolve starts in March 2025; the first two
    # events, both that month, are unpublished and have no files. Earlier
    # papers are on the council's Prior-Council-Meetings-and-Minutes page
    # (https://www.woorabinda.qld.gov.au/Our-Council/Prior-Council-Meetings-and-Minutes,
    # OpenCities accordions: a month each for January 2024 to February
    # 2025, minutes only for 2016-2023); reading it is left to the shared
    # content-page base being built for that shape.
    tenant = "woorabinda"
    resolve_from = datetime.date(2025, 3, 17)

    # Council meetings only, ordinary and special in one type. Left out is
    # the Trustee Meeting, the council sitting as trustee of its Deed of
    # Grant in Trust land: a separate body, and each kept meeting costs a
    # detail call on the shared api.resolve.red.
    meeting_types = re.compile(r"^Council$")

    # The type is just "Council"; the base class adds "Special" from the
    # event name, which turns "Ordinary Council" into "Special Council".
    meeting_type_names = {"Council": "Ordinary Council"}

    def __init__(self):
        super().__init__("woorabinda", "QLD")

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
                f"its Prior-Council-Meetings-and-Minutes page, which this scraper "
                f"does not read yet"
            )
        return []
