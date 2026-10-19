"""The OpenCities listing paths that no cassette exercises.

Cassettes are recorded unfiltered, but production passes one year, and for a
postback-driven council (mornington_peninsula) the filtered path is different
code: a year-filter postback, then pager postbacks that have to go to the
filtered page's own form action. Posting them to the bare listing URL drops
the filter and silently returns other years' meetings instead—the failure
these fakes reproduce.
"""

import json
import logging
import re

import pytest
import requests

from aus_council_scrapers.opencities import Listing, OpenCitiesMeetingsScraper
from tests.cassette import PlaybackFetcher

LISTING = "https://council.example/meetings"
FILTERED = LISTING + "?dlv_OC%20CL%20Public%20Meetings=(dd_OC%20Year=2025)"

PAGE_SELECT = "ctl10$ctl00$ctl08"
GO = "ctl10$ctl00$ctl09"
YEAR_SELECT = "ctl10$ctl00$ctl18$ctl00$ctl00"
FILTER_SEARCH = "ctl10$ctl00$ctl19"
SITE_SEARCH = "ctl07$btnSearch"


def _page(action: str, pages: int, rows: list[tuple[str, str]], year="") -> str:
    """A listing page shaped like the real module: the site search box first,
    then the pager, then the filter's own selects and Search button."""
    items = "".join(
        f"""<div class="accordion-list-item-container">
              <a class="accordion-trigger" data-cvid="{cvid}">
                <span class="minutes-date">{date}</span>
                <span class="meeting-type">Council Meeting</span></a></div>"""
        for date, cvid in rows
    )
    page_options = "".join(
        f"<option value='{n}'>{n}</option>" for n in range(1, pages + 1)
    )
    year_options = "".join(
        f"<option value='{y}'{' selected' if y == year else ''}>{y}</option>"
        for y in ("2026", "2025")
    )
    return f"""<html><body><form id="mainForm" action="{action}">
      <input type="hidden" name="__SEAMLESSVIEWSTATE" value="state-{year or 'any'}">
      <input type="text" name="ctl07$txtSearch" value="">
      <input type="submit" name="{SITE_SEARCH}" value="Search">
      <div class="seamless-pagination seamless-pagination-count-{pages}"></div>
      <select name="{PAGE_SELECT}">{page_options}</select>
      <input type="submit" name="{GO}" value="Go">
      <select name="{YEAR_SELECT}"><option value="">Any Year</option>{year_options}</select>
      <input type="submit" name="{FILTER_SEARCH}" value="Search">
      {items}
    </form></body></html>"""


def _payload(cvid: str) -> str:
    html = f'<div class="meeting-attachments"><a href="/files/{cvid}-agenda.pdf">Council Meeting Agenda</a></div>'
    return json.dumps({"html": html})


class _Council(PlaybackFetcher):
    """A fake site. Each answer depends on what was posted, like the real one."""

    def __init__(self, routes):
        super().__init__([])
        self.routes = routes
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        match = re.search(r"cvid=([\w-]+)", url)
        if match:
            return _payload(match.group(1))
        return self.routes(url, method, kwargs.get("data") or {})


class _Postback(OpenCitiesMeetingsScraper):
    def __init__(self):
        super().__init__("example_oc", "VIC", LISTING)


class _Dlv(_Postback):
    list_name = "OC CL Public Meetings"


UNFILTERED_1 = [("10 March 2026", "a"), ("02 December 2025", "b")]
UNFILTERED_2 = [("10 February 2026", "c"), ("11 January 2026", "d")]
FILTERED_1 = [("02 December 2025", "b"), ("04 November 2025", "e")]
FILTERED_2 = [("07 October 2025", "f"), ("09 September 2025", "g")]


def test_postback_year_filter_pages_within_the_filtered_result():
    def routes(url, method, data):
        if method == "GET" and url == LISTING:
            return _page(LISTING, 2, UNFILTERED_1)
        if method == "POST" and url == LISTING and data.get(FILTER_SEARCH):
            if data.get(YEAR_SELECT) == "2025":
                return _page(FILTERED, 2, FILTERED_1, year="2025")
        if method == "POST" and data.get(PAGE_SELECT) == "2" and data.get(GO):
            # The bare URL ignores the filter and serves unfiltered page 2.
            if url == FILTERED and data.get(YEAR_SELECT) == "2025":
                return _page(FILTERED, 2, FILTERED_2, year="2025")
            return _page(LISTING, 2, UNFILTERED_2)
        # Anything else, e.g. pressing the site-wide Search button, is a
        # search of the website rather than of the listing.
        return _page(LISTING, 2, UNFILTERED_1)

    scraper = _Postback()
    scraper.fetcher = _Council(routes)
    scraper.years_filter = [2025]

    dates = [m.date for m in scraper.scraper()]

    assert dates == [
        "02 December 2025",
        "04 November 2025",
        "07 October 2025",
        "09 September 2025",
    ]


def test_unrecognised_list_name_is_reported_not_paged_year_by_year(caplog):
    # A list name the site does not know is ignored, and every dlv URL serves
    # the unfiltered first page of a 16-page listing.
    def routes(url, method, data):
        return _page(LISTING, 16, UNFILTERED_1)

    scraper = _Dlv()
    fetcher = _Council(routes)
    scraper.fetcher = fetcher
    scraper.years_filter = [2025]

    with caplog.at_level(logging.WARNING):
        dates = [m.date for m in scraper.scraper()]

    assert dates == ["02 December 2025"]
    assert not [u for u in fetcher.requested if "pageindex" in u]
    assert "is list_name 'OC CL Public Meetings' still right?" in caplog.text


def test_blocked_listing_raises_rather_than_returning_no_meetings():
    # A council that refuses the runner (a WAF 403, a 5xx) must fail the run.
    # Returning [] would count it among the ok councils with 0 meetings.
    def routes(url, method, data):
        if url == LISTING:
            raise requests.HTTPError("403 Client Error: Forbidden")
        return _page(LISTING, 1, UNFILTERED_1)

    scraper = _Dlv()
    scraper.fetcher = _Council(routes)
    scraper.years_filter = [2025]

    with pytest.raises(requests.HTTPError):
        scraper.scraper()


def test_untrusted_year_filter_pages_newest_first_and_stops_at_older_years():
    # Blacktown's year filter drops most meetings, so its listings are
    # filtered by meeting type only and paged until a page predates the
    # wanted year. Production asks for one year: walking all five pages
    # would cost the whole history every night, and stopping after the first
    # would lose the rest of the year. Cassettes are recorded unfiltered, so
    # none of them exercises the stop.
    type_filter = "(dd_OC%20Meeting%20Type=Minutes%20of%20the%20Ordinary%20Meeting)"
    pages = {
        1: [("10 February 2026", "a"), ("10 December 2025", "b")],
        2: [("12 November 2025", "c"), ("10 January 2024", "d")],
        3: [("06 December 2023", "e"), ("08 November 2023", "f")],
        4: [("11 October 2023", "g")],
        5: [("13 September 2023", "h")],
    }

    def routes(url, method, data):
        assert type_filter in url, url
        match = re.search(r"\(pageindex=(\d+)\)", url)
        return _page(LISTING, 5, pages[int(match.group(1)) if match else 1])

    class _ByType(_Dlv):
        def main_listing(self):
            return Listing(LISTING, self.list_name, filters=type_filter, by_year=False)

    scraper = _ByType()
    fetcher = _Council(routes)
    scraper.fetcher = fetcher
    scraper.years_filter = [2025]

    dates = [m.date for m in scraper.scraper()]

    assert dates == ["10 December 2025", "12 November 2025"]
    paged = [
        re.search(r"pageindex=(\d+)", url).group(1)
        for url in fetcher.requested
        if "pageindex" in url
    ]
    # Page 2 ends in 2024, so nothing after it can be from 2025.
    assert paged == ["2"]


def test_year_filtered_first_page_is_fetched_once_and_bare_page_never():
    # Unley, Onkaparinga and Cambridge read the year dropdown off the
    # year-filtered page, which carries it too. Fetching the bare page as
    # well, or the filtered page twice, costs a request a listing every
    # night. Cassettes are recorded unfiltered, so none of them sees this.
    filtered_2 = FILTERED.replace("2025)", "2025)(pageindex=2)")

    def routes(url, method, data):
        assert url != LISTING, "the bare first page should not be fetched"
        if url == FILTERED:
            return _page(FILTERED, 2, FILTERED_1, year="2025")
        if url == filtered_2:
            return _page(FILTERED, 2, FILTERED_2, year="2025")
        raise AssertionError(url)

    class _YearFirst(_Dlv):
        year_filtered_first_page = True

    scraper = _YearFirst()
    fetcher = _Council(routes)
    scraper.fetcher = fetcher
    scraper.years_filter = [2025]

    dates = [m.date for m in scraper.scraper()]

    assert dates == [
        "02 December 2025",
        "04 November 2025",
        "07 October 2025",
        "09 September 2025",
    ]
    listing = [u for u in fetcher.requested if "cvid=" not in u]
    assert listing == [FILTERED, filtered_2]


def test_a_wanted_years_listing_failing_raises_too():
    # Production asks for one year, so losing that year's first page loses
    # everything, exactly as a blocked listing does.
    def routes(url, method, data):
        if "dd_OC%20Year=2025" in url:
            raise requests.HTTPError("503 Server Error")
        return _page(LISTING, 1, UNFILTERED_1)

    scraper = _Dlv()
    scraper.fetcher = _Council(routes)
    scraper.years_filter = [2025]

    with pytest.raises(requests.HTTPError):
        scraper.scraper()
