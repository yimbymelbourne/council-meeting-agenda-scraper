"""Tests for the judgement calls in the shared Alyka helpers.

The six WA cassettes prove the scrapers reproduce what they recorded, but a
re-record accepts whatever the helpers now say. These pin the two decisions a
re-record would not question: which date a hand-typed title means, and when a
linked file belongs to some other meeting.
"""

import datetime

import pytest

from aus_council_scrapers.alyka import AlykaScraper, find_date, names_another_year


@pytest.mark.parametrize(
    "title,expected",
    [
        # A meeting adjourned across nights is dated by its first.
        ("Minutes Ordinary Meeting of the Council 8 & 9 December 2020", "2020-12-08"),
        (
            "Minutes Ordinary Meeting of the Council 15, 22 & 29 September 2020",
            "2020-09-15",
        ),
        # Swan's three heading shapes.
        ("February 2, 2026 - Annual Meeting of Electors", "2026-02-02"),
        ("February, 12 2020 Ordinary Meeting", "2020-02-12"),
        ("October 14 ,2026 Ordinary Meeting of Council", "2026-10-14"),
        # Misspelt months, all from real titles.
        ("DAU - Minutes - 9 Decemeber 2025", "2025-12-09"),
        ("8 Septembe 2026 - Briefing Session - Agenda inc att.pdf", "2026-09-08"),
        # "Marshall" is not March.
        ("Lot 3 Marshall 12 2026", None),
        # Abbreviations are months.
        ("Ordinary Council Meeting - 27 Oct 2026", "2026-10-27"),
    ],
)
def test_find_date(title, expected):
    found = find_date(title)
    assert (found[0].isoformat() if found else None) == expected


@pytest.mark.parametrize(
    "url,year,expected",
    [
        # Melville's 16 May 2023 meeting links the May 2026 minutes.
        (
            "https://x/getContentAsset/a/b/Minutes-19-May-2026-OMC.pdf?language=en",
            2023,
            True,
        ),
        ("https://x/Metro-Outer-JDAP-211-Minutes-November-21,-2022.pdf", 2023, True),
        # A compact date is still a date.
        ("https://x/20240116-MO-JDAP-293-Agenda.pdf", 2024, False),
        # A development application's lodgement year is not the meeting's.
        ("https://x/20240116-MO-JDAP-293-Agenda-(DA-696-2023).pdf", 2024, False),
        # Several years named, one of them the meeting's.
        ("https://x/2024-2025-EGM-Agenda-23-March-2026.pdf", 2026, False),
        # No year at all is given the benefit of the doubt.
        ("https://x/CJ200211_AGN.pdf", 2020, False),
    ],
)
def test_names_another_year(url, year, expected):
    assert names_another_year(url, year) is expected


class _Scraper(AlykaScraper):
    def __init__(self):
        super().__init__("alyka_test", "WA", "https://example.invalid")

    def scraper(self):
        return []


def _fetch_failing(bad_years):
    def fetch(year):
        if year in bad_years:
            raise ConnectionError(f"{year} refused")
        return f"page {year}"

    return fetch


def test_each_year_skips_a_failed_year_among_several():
    scraper = _Scraper()
    answers = list(scraper._each_year([2026, 2025], _fetch_failing({2025})))
    assert answers == [(2026, "page 2026")]


def test_each_year_raises_when_every_year_fails():
    # Production asks for one year. If that year fails, returning [] would put
    # the council in okCouncils with 0 meetings, so the error must surface.
    scraper = _Scraper()
    with pytest.raises(ConnectionError, match="2026 refused"):
        list(scraper._each_year([2026], _fetch_failing({2026})))
