import datetime
import re

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    DocsPublishedScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.councilconnect import CouncilConnectArchive

SITE = "https://www.nannup.wa.gov.au"

# The first meeting the Shire published through DocsPublished, and the last
# in its CouncilConnect module: the 23 July 2026 Ordinary Council Meeting is
# in both (checked 20 Oct 2026).
DOCSPUBLISHED_FROM = datetime.date(2026, 7, 23)

# The CouncilConnect module's time field holds the upload time through 2020:
# 13 of that year's 15 timed meetings say 8:00 to 10:10 AM or 2:45 PM, where
# their agendas say 4.30pm, 5.00pm or 5.30pm. From 2021 it agrees with the
# agenda for every meeting (each agenda read 20 Oct 2026). So meetings
# before 2021 carry no time.
_ARCHIVE_TIMES_FROM = datetime.date(2021, 1, 1)

# The CouncilConnect module names its Council types the long way round; the
# DocsPublished names are used, so a meeting type reads the same either side
# of the move.
_ARCHIVE_NAMES = {
    "Ordinary Meeting of Council": "Ordinary Council Meeting",
    "Special Meeting of Council": "Special Council Meeting",
}

# DocsPublished records the council got wrong, by viewer page, each read
# against its PDFs (20 Oct 2026).
_DOCSPUBLISHED_FIXES = {
    # Monday 14 September 2026 is stamped 2:30 PM; its agenda and minutes
    # both say 4:30 pm, as does the agenda's filename.
    "https://docspublished.com.au/nannup/document/"
    "9a8800b1-7fb7-4d3a-91ab-2ce490a8e957": {"time": "4:30 PM"},
    # Thursday 10 September 2026 had two special meetings, filed as one
    # record stamped at midnight. The agenda is the 3:55 pm meeting's, held
    # to let the CEO advise on the UCI Gravel World Championship item. The
    # minutes are the 3:30 pm meeting's, a single page saying it did not
    # take place and was adjourned to 14 September. So the record is the
    # 3:55 pm meeting, whose own minutes are not published, with its agenda
    # alone.
    "https://docspublished.com.au/nannup/document/"
    "df926da3-bb96-4390-bb61-fdeb17a94387": {"time": "3:55 PM", "drop_minutes": True},
}

_NAME_WITH_TAIL = re.compile(
    r"^((?:Ordinary|Special) Council Meeting|Special Electors Meeting)\b.+$"
)


@register_scraper
class NannupScraper(DocsPublishedScraper):
    # One production year, measured 20 Oct 2026 from a home IP, alone: 29 s,
    # most of it the CouncilConnect module's meeting pages at the site's 2 s
    # spacing. It falls to the DocsPublished calls alone from 2027. Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 29

    # The Shire moved its agendas and minutes to DocAssembler's
    # DocsPublished in mid-2026. Its CouncilConnect meetings module, at
    # /council-meetings/past/<year>, holds 2018 to 23 July 2026 and lists no
    # upcoming meetings any more; DocsPublished holds 23 July 2026 on. So
    # DocsPublished is read for meetings from 23 July 2026 and the module
    # for those before it. 2026 needs both: five DocsPublished requests, two
    # listing pages and a request per module meeting.
    publishing_slug = "nannup"

    def __init__(self):
        super().__init__("nannup", "WA")

    def scraper(self) -> list[ScraperReturn]:
        results = [
            record
            for record in super().scraper()
            if record.date >= DOCSPUBLISHED_FROM.isoformat()
        ]
        for record in results:
            # A meeting stamped at local midnight has a date and no time;
            # "12:00 AM" would claim one.
            if record.time == "12:00 AM":
                record.time = None
            fix = _DOCSPUBLISHED_FIXES.get(record.webpage_url)
            if fix:
                record.time = fix["time"]
                if fix.get("drop_minutes"):
                    record.minutes_url = None

        years_filter = getattr(self, "years_filter", None)
        wanted = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        before = {year for year in wanted if year <= DOCSPUBLISHED_FROM.year}
        if not before:
            return results

        # Every type is read, through the all-types listing: the Ordinary
        # meetings' own year listing answers 404 (checked 20 Oct 2026), and
        # 2026 has nothing but Council meetings and the electors' meeting in
        # it. The audit committee's handful a year cost a request each only
        # in years production no longer asks for.
        try:
            archive = CouncilConnectArchive(
                self, SITE, untimed_before=_ARCHIVE_TIMES_FROM
            ).read(before, before=DOCSPUBLISHED_FROM)
        except Exception as e:
            # In 2026 a failed archive must not throw away DocsPublished's
            # meetings, and must not hide behind them either: in an earlier
            # year it is the only source.
            if not results:
                raise
            self.logger.warning(
                f"{self.council_name}: returning {len(results)} DocsPublished "
                f"meeting(s) without the CouncilConnect archive, which failed: {e}"
            )
            return results
        for record in archive:
            record.name = _ARCHIVE_NAMES.get(record.name, record.name)
            # Headings the module could not reduce to a type: "Special
            # Council Meeting to be held on ..." (11 July and 29 August 2024)
            # and "Special Electors Meeting - Vaccination Mandates" (31 March
            # 2022). The meeting type is the part before the tail.
            tail = _NAME_WITH_TAIL.match(record.name or "")
            if tail:
                record.name = tail.group(1)
        return sorted(archive + results, key=lambda r: r.date)
