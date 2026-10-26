"""Rules in the national item C-2 scrapers that the recorded fixtures cannot pin.

A fixture records the site as it is, so it never shows a page whose markup
has moved. Each of these scrapers reads a page that, after a redesign, would
still load but parse to nothing—and an empty list reads downstream as a
council that held no meetings. These tests pin that such a page raises
instead. The Wodonga tests pin when a month-only 2020 paper may borrow a day
from a sibling file, which a re-record would otherwise accept silently.
"""

import pytest

from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.nsw.hawkesbury import HawkesburyScraper
from aus_council_scrapers.scrapers.nsw.tamworth import TamworthScraper
from aus_council_scrapers.scrapers.vic.greater_shepparton import (
    GreaterSheppartonScraper,
)
from aus_council_scrapers.scrapers.vic.wodonga import WodongaScraper


class _Pages(Fetcher):
    """Serves a fixed page per URL, or one page for every URL."""

    def __init__(self, pages: dict[str, str] | str):
        self.pages = pages

    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        if isinstance(self.pages, str):
            return self.pages
        return self.pages[url]

    def get_selenium_driver(self):
        raise AssertionError("plain HTML only")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("plain HTML only")


def _run(scraper, pages, years):
    scraper.fetcher = _Pages(pages)
    scraper.years_filter = years
    return scraper.scraper()


# --------------------------------------------------------------------------
# A page that loads but parses to nothing raises
# --------------------------------------------------------------------------


def test_hawkesbury_page_without_its_file_links_raises():
    # The year is still readable from a file URL, but the links have lost
    # the class the parser keys on.
    html = '<h4>3 February 2026</h4><a href="/x/current/business-papers-2026/a.pdf">Agenda</a>'
    with pytest.raises(RuntimeError, match="related-document__link"):
        _run(HawkesburyScraper(), html, [2026])


def test_hawkesbury_page_without_dated_headings_raises():
    html = (
        '<h3>3 February 2026</h3><a class="related-document__link" '
        'href="/x/current/business-papers-2026/a.pdf">Agenda</a>'
    )
    with pytest.raises(RuntimeError, match="dated meeting headings"):
        _run(HawkesburyScraper(), html, [2026])


def test_shepparton_year_page_without_sections_raises():
    index = "https://greatershepparton.com.au/council/governance/council-meetings/minutes-agendas"
    year = index + "/2026-agendas-and-minutes"
    pages = {
        index: f'<a href="{year}">2026</a>',
        year: "<h3>24 February 2026 - Council Meeting</h3><a href='a.pdf'>Agenda</a>",
    }
    with pytest.raises(RuntimeError, match="no meeting sections"):
        _run(GreaterSheppartonScraper(), pages, [2026])


def test_tamworth_table_without_rows_raises():
    html = '<table id="tableDocList4438"><tr><th>Name</th><th>Date</th></tr></table>'
    with pytest.raises(RuntimeError, match="no document rows"):
        _run(TamworthScraper(), html, [2026])


def _wodonga(*sections: tuple[str, list[tuple[str, str]]]) -> str:
    body = ""
    for title, files in sections:
        buttons = "".join(
            f'<div class="lrg-btn"><aside><div class="col-10">{label}</div></aside>'
            f'<a href="/Portals/0/Attachments/{filename}"></a></div>'
            for label, filename in files
        )
        body += (
            f'<div class="content--toggle--item"><a href="#">{title}</a>{buttons}</div>'
        )
    return f"<html><body>{body}</body></html>"


def test_wodonga_sections_without_file_buttons_raise():
    html = '<div class="content--toggle--item"><a href="#">2026 past agendas</a></div>'
    with pytest.raises(RuntimeError, match="lrg-btn"):
        _run(WodongaScraper(), html, [2026])


# --------------------------------------------------------------------------
# Wodonga's month-only 2020 papers
# --------------------------------------------------------------------------


def test_wodonga_month_only_minutes_take_the_one_day_a_sibling_names():
    html = _wodonga(
        (
            "2020 past minutes",
            [
                ("04 - April 2020 ordinary meeting minutes", "april_minutes.pdf"),
                (
                    "04 - April 2020 question time",
                    "Question_time_council_meeting_of_20_April_2020-1.pdf",
                ),
            ],
        )
    )
    results = _run(WodongaScraper(), html, [2020])
    assert [(r.date, r.minutes_url.rsplit("/", 1)[-1]) for r in results] == [
        ("2020-04-20", "april_minutes.pdf")
    ]


def test_wodonga_month_only_minutes_never_take_a_dated_meetings_day():
    # June 2020: the only day named is the ordinary meeting's own, so the
    # month-only special meeting is left out rather than merged into it.
    html = _wodonga(
        (
            "2020 past minutes",
            [
                ("06 - June 2020 special meeting minutes", "june_special.pdf"),
                ("06 - June 29th, 2020 council meeting minutes", "june_ordinary.pdf"),
            ],
        )
    )
    results = _run(WodongaScraper(), html, [2020])
    assert [(r.date, r.name) for r in results] == [("2020-06-29", "Council Meeting")]
    assert results[0].minutes_url.endswith("june_ordinary.pdf")


def test_wodonga_month_only_minutes_with_no_named_day_are_left_out():
    html = _wodonga(
        (
            "2020 past minutes",
            [("12 - December council meeting minutes", "December_minutes.pdf")],
        )
    )
    assert _run(WodongaScraper(), html, [2020]) == []
