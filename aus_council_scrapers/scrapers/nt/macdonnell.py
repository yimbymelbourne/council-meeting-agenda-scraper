from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper

# The meetings entered before December 2024 (migrated in one batch: their
# pages sit under the plural slug, ".../ordinary-council-meetings/<id>") all
# read "6:00 PM", the module's default, not the hour. The Council meets in
# the morning: the minutes of 30 April 2020 say it opened "AT 10:00AM", of 25
# August 2023 "AT 10:02AM", of 25 October 2024 "AT 10:00 AM". The meeting
# page gives no other time, so these are emptied. The first meeting entered
# by hand, 13 December 2024, reads 10:00 AM, as do most since.
_PLACEHOLDER_TIME = "6:00 PM"
_PLACEHOLDER_BEFORE = "2024-12-01"

# Dates whose date field is wrong, with the time the agenda gives. The 29
# May 2026 Special reads "9:00 PM"; its agenda opens "on Friday 29 May 2026
# at 10:00 AM". Only replaced while the field still says the wrong time.
_TIME_CORRECTIONS = {("2026-05-29", "9:00 PM"): "10:00 AM"}


@register_scraper
class MacDonnellScraper(CouncilConnectScraper):
    """MacDonnell Regional Council—documents on each meeting's own page.

    Council meetings only. The all-types listing is dominated by the
    thirteen community Local Authorities—advisory bodies under the NT Local
    Government Act, 52 to 68 meetings a year—plus the Finance and Risk and
    Audit committees. Every meeting costs a request, so reading them would
    put a production year near 80 requests. Ordinary and Special Council
    meetings are six to eight a year.

    `/council-meetings/` is a page of links here, not the upcoming list,
    so upcoming meetings are read from each type's own page, which lists
    them with dated buttons.

    The Council meets over two days now and then ("Ordinary Council Meeting
    25-26 September 2025"); the date is the first day, from the date field.

    Times before December 2024 are emptied; see `_PLACEHOLDER_TIME`.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-council-meetings": "Special Council Meeting",
    }
    upcoming_path = (
        "/council-meetings/ordinary-council-meetings",
        "/council-meetings/special-council-meetings",
    )

    # One production year, measured 20 Oct 2026 from a home IP: 22 s for
    # 12 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 22

    def __init__(self):
        super().__init__("macdonnell", "NT", "https://www.macdonnell.nt.gov.au")

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()
        for record in results:
            if record.time == _PLACEHOLDER_TIME and record.date < _PLACEHOLDER_BEFORE:
                record.time = None
            record.time = _TIME_CORRECTIONS.get((record.date, record.time), record.time)
        return results
