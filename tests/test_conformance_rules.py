"""Tests for the conformance rules themselves.

`test_conformance.py` runs the rules over the real fixtures, which proves
whether today's scrapers pass but not what the rules actually mean. These pin
the meaning, so a threshold cannot drift without a test saying so.
"""

from aus_council_scrapers import clock
from aus_council_scrapers.conformance import assess


def _meeting(date, **overrides):
    row = {
        "name": "Ordinary Council",
        "date": date,
        "time": None,
        "location": None,
        "webpage_url": "https://example.infocouncil.biz/",
        "agenda_url": f"https://example.infocouncil.biz/{date}-AGN.PDF",
        "minutes_url": f"https://example.infocouncil.biz/{date}-MIN.PDF",
        "agenda_html_url": None,
        "minutes_html_url": None,
        "download_url": f"https://example.infocouncil.biz/{date}-AGN.PDF",
    }
    row.update(overrides)
    return row


def _spanning(years):
    return [_meeting(f"01 Mar {y}") for y in years]


def test_a_short_history_does_not_make_a_scraper_incomplete():
    """A council that publishes nothing before 2022 cannot be scraped back to
    2020, however good the scraper. Judging it on that measured the council,
    not the code — this is Banyule, verified against their live year filter.
    """
    with clock.frozen("2026-08-20"):
        result = assess("banyule-like", _spanning([2022, 2023, 2024, 2025, 2026]))
    assert result.status == "complete"
    assert not result.coverage


def test_the_span_is_still_reported_even_when_it_does_not_affect_status():
    """Dropping the rule must not hide the fact, or a scraper that silently
    stops reaching older years becomes invisible."""
    with clock.frozen("2026-08-20"):
        result = assess("recent-only", _spanning([2024, 2025, 2026]))
    assert result.span == "2024-2026"


def test_too_few_years_is_still_incomplete():
    with clock.frozen("2026-08-20"):
        result = assess("thin", _spanning([2025, 2026]))
    assert result.status == "partial"
    assert any("year(s)" in note for note in result.coverage)


def test_stale_output_is_incomplete_however_long_the_history():
    """Nothing newer than last year means the scraper has stopped keeping up,
    which is a real failure rather than a publishing limit."""
    with clock.frozen("2026-08-20"):
        result = assess("stale", _spanning([2020, 2021, 2022, 2023, 2024, 2025]))
    assert result.status == "partial"
    assert "nothing newer than 2025" in result.coverage


def test_minutes_are_still_required_on_past_meetings():
    meetings = [
        _meeting(f"01 Mar {y}", minutes_url=None) for y in (2024, 2025, 2026)
    ]
    with clock.frozen("2026-08-20"):
        result = assess("no-minutes", meetings)
    assert "no minutes on any past meeting" in result.coverage


def test_invariants_still_fail_regardless_of_coverage():
    """Loosening coverage must not loosen correctness."""
    meetings = _spanning([2024, 2025, 2026])
    meetings.append(dict(meetings[0]))  # exact duplicate
    with clock.frozen("2026-08-20"):
        result = assess("dupes", meetings)
    assert result.status == "broken"
    assert any("emitted twice" in note for note in result.invariants)
