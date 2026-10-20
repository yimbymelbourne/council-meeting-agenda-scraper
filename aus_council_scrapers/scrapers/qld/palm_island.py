import datetime
import re

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.resolve import ResolveScraper

_BUDGET = re.compile(r"\bbudget\b", re.IGNORECASE)


@register_scraper
class PalmIslandScraper(ResolveScraper):
    # Palm Island moved to Resolve (tenant `palmcouncil`) for its 28 January
    # 2026 meetings. Its older papers are on two OpenCities content pages,
    # Meeting-Agendas (2022-2025) and Meeting-minutes (2016-2025), under
    # https://www.palmcouncil.qld.gov.au/My-Council/Council-Meetings;
    # reading them is left to the shared content-page base being built for
    # that shape, and the minutes there are titled by month alone, so their
    # meeting dates are not known from the page.
    tenant = "palmcouncil"
    resolve_from = datetime.date(2026, 1, 28)

    # Ordinary Council only. Left out is the Land Trust, the council sitting
    # as trustee of the island's Deed of Grant in Trust land, which meets an
    # hour before each Ordinary meeting: it is a separate body, and keeping
    # it would double the detail calls a year costs on the shared
    # api.resolve.red.
    meeting_types = re.compile(r"^Ordinary Council$")

    def __init__(self):
        super().__init__("palm_island", "QLD")

    def _meeting_name(self, event: dict) -> str:
        # The budget is adopted at its own meeting filed under the Ordinary
        # type, the same afternoon as an Ordinary meeting ("Statutory Budget
        # Meeting - 30 June 2026"), so the type alone would give two Ordinary
        # Council meetings that day. Other events are named from the type,
        # since the free-typed names include "One Time Event" (30 September
        # 2026, an Ordinary meeting).
        if _BUDGET.search(event.get("name") or ""):
            return "Budget Meeting"
        return super()._meeting_name(event)

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
                f"its Meeting-Agendas and Meeting-minutes pages, which this scraper "
                f"does not read yet"
            )
        return []
