"""Kingborough's meeting boxes carry no meeting type.

Special meetings are named from when they fall: an extra meeting between two
fortnightly Monday meetings is special, while a meeting moved off a public
holiday Monday leaves a three- or four-week gap between the Mondays around it.
The recorded fixture holds four special meetings, but a re-record would accept
a regression silently, so the rule is pinned here through `scraper()`.
"""

import datetime

from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.tas.kingborough import KingboroughScraper

_UPLOADS = "https://www.kingborough.tas.gov.au/wp-content/uploads/2023/06"


def _box(day: datetime.date) -> str:
    stamp = f"{day.day}-{day:%B}-{day.year}"
    return f"""
    <div class="box-inner box-halved box-rounded box-yellow">
      <div class="box-top-half box-meeting-date">
        <span class="box-meeting-day">{day.day}</span>
        <span class="box-meeting-month">{day:%B}</span>
        <span class="box-meeting-year">{day.year}</span>
      </div>
      <div class="box-bottom-half">
        <a href="{_UPLOADS}/Agenda-{stamp}-Public-Copy.pdf">Agenda</a>
        <a href="{_UPLOADS}/Minutes-{stamp}-Public-Copy.pdf">Minutes</a>
      </div>
    </div>"""


class _OnePage(Fetcher):
    def __init__(self, html: str):
        self.html = html

    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        return self.html

    def get_selenium_driver(self):
        raise AssertionError("Kingborough is plain HTML")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("Kingborough is plain HTML")


def test_an_extra_meeting_between_fortnightly_mondays_is_special():
    days = [
        # Newest first, as the archive lists them. 13 June 2023 (a Tuesday)
        # sits between the 5 and 19 June Mondays; 3 April 2024 (a Wednesday,
        # after Easter Monday) replaces a Monday, so its Mondays are four
        # weeks apart.
        datetime.date(2024, 4, 15),
        datetime.date(2024, 4, 3),
        datetime.date(2024, 3, 18),
        datetime.date(2023, 6, 19),
        datetime.date(2023, 6, 13),
        datetime.date(2023, 6, 5),
        datetime.date(2022, 12, 19),
    ]
    scraper = KingboroughScraper()
    scraper.fetcher = _OnePage(f"<html><body>{''.join(_box(d) for d in days)}</body></html>")
    scraper.years_filter = [2023, 2024]
    names = {r.date: r.name for r in scraper.scraper()}
    assert names["2023-06-13"] == "Special Council Meeting"
    assert names["2024-04-03"] == "Council Meeting"
    assert names["2023-06-05"] == "Council Meeting"
