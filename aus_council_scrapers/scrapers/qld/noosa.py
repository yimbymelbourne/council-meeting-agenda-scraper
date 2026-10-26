import datetime
import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class NoosaScraper(ResolveScraper):
    # Noosa's meetings page links the Resolve portal. Noosa moved to Resolve
    # for its 11 April 2023 Planning & Environment Committee. Earlier papers
    # (2014 to March 2023) are on an OpenCities archive page,
    # https://www.noosa.qld.gov.au/About-Council/Councillors-and-meetings/Council-Meetings-and-Minutes/Archived-Council-Agendas-and-Minutes,
    # which this scraper does not read yet, so its history starts at the move.
    tenant = "noosa"
    resolve_from = datetime.date(2023, 4, 11)

    # Council (ordinary and special) and the two bodies that decide planning
    # business. The Planning & Environment Committee sat until 7 April 2026.
    # The General Committee has decided development applications all along
    # (material change of use and reconfiguring-a-lot applications, Planning
    # and Environment Court appeals, the monthly report of applications
    # decided under delegation) and took over all planning business from
    # May 2026. Left out is the Services & Organisation Committee; each kept
    # meeting costs a request to learn which documents it has. Anchored,
    # which also drops the tenant's "Test Live Stream" event.
    meeting_types = re.compile(
        r"^(Ordinary Meeting|Special Meeting"
        r"|Planning & Environment Committee Meeting|General Committee Meeting)$"
    )

    # One production year, measured 20 Oct 2026 from a home IP: 25 s for
    # 2025 (40 meetings, so about 43 requests: the listing pages and a
    # detail call per meeting) and 16 s for 2026 so far. Over the usual
    # 20-request aim because the General Committee meets monthly and
    # decides planning business, so it cannot be left out. Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 25

    def __init__(self):
        super().__init__("noosa", "QLD")
