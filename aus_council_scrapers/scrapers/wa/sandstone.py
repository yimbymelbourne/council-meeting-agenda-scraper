import datetime

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.datascape import DatascapeMeetingsScraper

# Shire of Sandstone. From 2023 an item per month's meetings ("2025 February
# Ordinary, Special and Electors Meetings"); for 2020-2022 one item per year
# ("All Council Meetings in 2020") holding every paper. Many papers are named
# by month only ("Agenda - March 2020"), so a meeting is kept only where a
# paper or its item names the day, or the day is in `known_meeting_dates`
# below; the rest are logged and left out. Where the title gives only the
# month, the item's Date: field is the meeting's day (Sandstone meets on
# Thursdays, and the dates checked all are), unless the item's own files name
# another day: the August 2025 meeting was moved to 1 September after it was
# listed for 28 August.
#
# Served direct (x-powered-by: ASP.NET), no CDN or WAF headers seen from a
# home IP. robots.txt: Allow / with Crawl-delay: 7.


def _d(year: int, month: int, day: int) -> datetime.date:
    return datetime.date(year, month, day)


@register_scraper
class SandstoneScraper(DatascapeMeetingsScraper):
    listing_url = "https://www.sandstone.wa.gov.au/council/meetings"
    category = "council-meetings"
    # Its own share is about 100 s (15 requests at the 7 s crawl delay)
    # for a production year, but it takes turns with the other councils on
    # Datascape's shared server, and the three together took 270-274 s
    # (20 Oct 2026). Set to the group's time so all three start first.
    expected_seconds = 275.0

    # The 2020-2022 papers, and one special agenda in 2023, are named by
    # month only, and nothing else on the site gives the day. These days are
    # from the papers' own covers: every agenda and its minutes were read on
    # 20 Oct 2026 and agree, except June 2022 (below). Those years are
    # closed, so the papers will not change; a paper re-uploaded under a new
    # name simply goes back to being dated, or left out, by the usual rules.
    known_meeting_dates = {
        ("ordinary", 2020, 2): _d(2020, 2, 27),
        ("ordinary", 2020, 3): _d(2020, 3, 26),
        ("ordinary", 2020, 4): _d(2020, 4, 23),
        ("ordinary", 2020, 5): _d(2020, 5, 28),
        ("ordinary", 2020, 6): _d(2020, 6, 25),
        ("ordinary", 2020, 7): _d(2020, 7, 23),
        ("ordinary", 2020, 8): _d(2020, 8, 27),
        ("ordinary", 2020, 9): _d(2020, 9, 24),
        ("ordinary", 2020, 10): _d(2020, 10, 22),
        ("ordinary", 2020, 11): _d(2020, 11, 26),
        ("ordinary", 2020, 12): _d(2020, 12, 17),
        ("ordinary", 2021, 2): _d(2021, 2, 25),
        ("ordinary", 2021, 3): _d(2021, 3, 25),
        ("ordinary", 2021, 4): _d(2021, 4, 22),
        ("ordinary", 2021, 5): _d(2021, 5, 27),
        ("ordinary", 2021, 6): _d(2021, 6, 24),
        ("ordinary", 2021, 7): _d(2021, 7, 22),
        ("ordinary", 2021, 8): _d(2021, 8, 26),
        # A Friday, on both covers.
        ("ordinary", 2021, 9): _d(2021, 9, 24),
        ("ordinary", 2021, 10): _d(2021, 10, 28),
        ("ordinary", 2021, 11): _d(2021, 11, 25),
        ("ordinary", 2021, 12): _d(2021, 12, 16),
        # At 10 am, before that day's ordinary meeting at 1 pm.
        ("special", 2021, 12): _d(2021, 12, 16),
        ("ordinary", 2022, 2): _d(2022, 2, 24),
        ("ordinary", 2022, 3): _d(2022, 3, 24),
        ("ordinary", 2022, 4): _d(2022, 4, 28),
        ("ordinary", 2022, 5): _d(2022, 5, 26),
        # The June agenda is for Thursday 23 June, but the meeting was held
        # on Friday 8 July: its minutes say "Ordinary Council Meeting held on
        # Friday 08 July 2022" and confirm the minutes of 26 May, so no
        # meeting was held in between. Dated as held, as for August 2025.
        ("ordinary", 2022, 6): _d(2022, 7, 8),
        ("ordinary", 2022, 7): _d(2022, 7, 28),
        ("ordinary", 2022, 9): _d(2022, 9, 22),
        ("special", 2022, 9): _d(2022, 9, 14),
        ("ordinary", 2022, 10): _d(2022, 10, 27),
        ("ordinary", 2022, 11): _d(2022, 11, 24),
        ("ordinary", 2022, 12): _d(2022, 12, 15),
        ("special", 2023, 10): _d(2023, 10, 13),
    }

    def __init__(self):
        super().__init__("sandstone", "WA", "https://www.sandstone.wa.gov.au")
