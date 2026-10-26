"""Coolamon's two edges the cassette cannot show.

The council publishes only the next meeting's business paper, and none was
linked when the cassette was cut, so `_next_meeting` is fed a synthetic page
here. And from 1 January until the year's first paper is linked, the current
year has no meeting at all: that must be an empty year, not a failure.
"""

from __future__ import annotations

import datetime

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.pdf_dates import PdfText
from aus_council_scrapers.scrapers.nsw.coolamon import (
    _MEETINGS_URL,
    CoolamonScraper,
)
from tests.replay_cost import CountingPlayback, load_cassette

_PAGE = """<html><body><header><a href="/s/policy.pdf">Policy</a></header>
<main><p>Council next meeting will be held on Thursday, 19 November 2026
commencing at 3.00pm.</p>{link}</main></body></html>"""


class _Site:
    """The meetings page, and a business paper whose cover says `cover`."""

    def __init__(self, link: str, cover: str):
        self.page = _PAGE.format(link=link)
        self.cover = cover
        self.papers: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        assert url == _MEETINGS_URL
        return self.page

    def fetch_pdf_text(self, url, pages=1, partial=True, full_limit=None):
        self.papers.append(url)
        return PdfText(self.cover, complete=True, bytes_read=1)


def _next(link: str, cover: str):
    scraper = CoolamonScraper()
    scraper.fetcher = site = _Site(link, cover)
    return scraper._next_meeting({2026}), site


_NOVEMBER = '<a href="/s/businesspaper_november_2026.pdf">Business Paper</a>'


def test_business_paper_whose_cover_agrees():
    meeting, _ = _next(
        _NOVEMBER,
        "ORDINARY MEETING ... will be held in the Council Chambers, Coolamon on "
        "Thursday, 19th November 2026 at 3.00pm.",
    )
    assert meeting.date == "2026-11-19"
    assert meeting.time == "3:00pm"
    assert meeting.agenda_url.endswith("/s/businesspaper_november_2026.pdf")


def test_cover_overrules_the_page_when_they_differ():
    meeting, _ = _next(
        _NOVEMBER,
        "ORDINARY MEETING ... will be held in the Council Chambers, Coolamon on "
        "Thursday, 26th November 2026 at 3.00pm.",
    )
    assert meeting.date == "2026-11-26"


def test_cover_without_a_day_is_kept_when_the_link_names_the_month():
    meeting, _ = _next(_NOVEMBER, "THE COUNCIL OF THE SHIRE OF COOLAMON")
    assert meeting.date == "2026-11-19"


def test_last_meetings_paper_still_linked_is_left_out():
    # October's paper, not yet taken down: its cover gives no November day
    # and its name says October, so it is not November's agenda.
    meeting, _ = _next(
        '<a href="/s/businesspaper_october_2026.pdf">Business Paper</a>',
        "Thursday, 15th October 2026 at 3.00pm.",
    )
    assert meeting is None


def test_no_business_paper_linked_yet():
    meeting, site = _next('<a href="/council-policies">Policies</a>', "")
    assert meeting is None and site.papers == []


def _replay_2027(today: str):
    scraper = CoolamonScraper()
    replay, _ = load_cassette("coolamon")
    scraper.fetcher = CountingPlayback(replay, "coolamon")
    scraper.years_filter = [2027]
    with clock.frozen(today):
        return scraper.scraper()


def test_january_before_the_first_paper_is_an_empty_year():
    assert _replay_2027("2027-01-20") == []


def test_an_empty_year_after_march_still_fails():
    with pytest.raises(RuntimeError, match="no dated meeting"):
        _replay_2027("2027-05-01")


def test_frozen_clock_reaches_the_scraper():
    # Guards the two tests above: they mean nothing if the scraper reads
    # the real date.
    with clock.frozen("2027-01-20"):
        assert clock.today() == datetime.date(2027, 1, 20)
