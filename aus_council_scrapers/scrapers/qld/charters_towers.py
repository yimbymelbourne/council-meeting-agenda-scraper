import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class ChartersTowersScraper(ResolveScraper):
    # Charters Towers' Current-minutes-agendas page frames the Resolve
    # portal. The council moved to Resolve for its 16 November 2022 General
    # Meeting. Earlier papers (2016 to October 2022) are on
    # https://www.charterstowers.qld.gov.au/Council/Meetings-and-minutes/Archive-minutes-agendas,
    # which this scraper does not read yet, so its history starts at the move.
    tenant = "charterstowers"
    resolve_from = datetime.date(2022, 11, 1)

    # The General Meeting is Council's ordinary meeting; special and
    # statutory budget meetings are filed under either type. These are the
    # tenant's only two types, named so that a committee the council starts
    # publishing here cannot add a request per meeting to the nightly run
    # unasked.
    meeting_types = re.compile(r"^(General Meeting|Special Meeting of Council)$")

    def __init__(self):
        super().__init__("charters_towers", "QLD")

    def _meeting_name(self, event: dict) -> str:
        # The statutory budget meeting is filed under General Meeting in
        # 2023-2025 and under Special Meeting of Council in 2026, so its
        # type would name it two ways. Only the free-typed event name says
        # what it is: "Statutory Budget Meeting_25 June 2025", "Agenda for
        # CTRC Statutory BudgetMeeting". In June 2026 it also shares its day
        # with a separate Special Meeting of Council, which this keeps
        # apart.
        if re.search(r"budget", event.get("name") or "", re.IGNORECASE):
            return "Statutory Budget Meeting"
        return super()._meeting_name(event)
