"""Tests for merging a meeting split across two listing rows.

Some InfoCouncil sites list one meeting twice — once with its agenda, once
with its minutes. Merging them is only safe when the two rows do not
disagree, so the boundary matters more than the happy path.
"""

from aus_council_scrapers.base import ScraperReturn, _merge_split_meetings


def _meeting(**overrides):
    fields = dict(
        name="Ordinary Council",
        date="08 Dec 2022",
        time=None,
        webpage_url="https://example.infocouncil.biz/",
    )
    fields.update(overrides)
    return ScraperReturn(**fields)


def test_agenda_row_and_minutes_row_become_one_meeting():
    merged = _merge_split_meetings(
        [
            _meeting(minutes_url="https://x.test/MIN.PDF"),
            _meeting(agenda_url="https://x.test/AGN.PDF"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].agenda_url == "https://x.test/AGN.PDF"
    assert merged[0].minutes_url == "https://x.test/MIN.PDF"


def test_merging_fills_in_the_deprecated_download_url():
    merged = _merge_split_meetings(
        [
            _meeting(minutes_url="https://x.test/MIN.PDF"),
            _meeting(agenda_url="https://x.test/AGN.PDF"),
        ]
    )
    assert merged[0].download_url == "https://x.test/AGN.PDF"


def test_two_real_meetings_on_one_night_are_not_merged():
    """A council can hold two special meetings the same evening. Each has its
    own agenda, so the rows conflict and both must survive."""
    merged = _merge_split_meetings(
        [
            _meeting(name="Special Council", agenda_url="https://x.test/A1.PDF"),
            _meeting(name="Special Council", agenda_url="https://x.test/A2.PDF"),
        ]
    )
    assert len(merged) == 2


def test_different_dates_are_never_merged():
    merged = _merge_split_meetings(
        [
            _meeting(date="08 Dec 2022", agenda_url="https://x.test/A.PDF"),
            _meeting(date="24 Nov 2022", minutes_url="https://x.test/M.PDF"),
        ]
    )
    assert len(merged) == 2


def test_html_variants_merge_too():
    merged = _merge_split_meetings(
        [
            _meeting(minutes_url="https://x.test/M.PDF", minutes_html_url="https://x.test/M.htm"),
            _meeting(agenda_url="https://x.test/A.PDF", agenda_html_url="https://x.test/A.htm"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].agenda_html_url == "https://x.test/A.htm"
    assert merged[0].minutes_html_url == "https://x.test/M.htm"


def test_time_and_location_are_taken_from_whichever_row_has_them():
    merged = _merge_split_meetings(
        [
            _meeting(minutes_url="https://x.test/M.PDF"),
            _meeting(
                agenda_url="https://x.test/A.PDF",
                time="7:00 PM",
                location="Council Chambers",
            ),
        ]
    )
    assert merged[0].time == "7:00 PM"
    assert merged[0].location == "Council Chambers"


def test_ordering_is_preserved():
    merged = _merge_split_meetings(
        [
            _meeting(date="08 Dec 2022", agenda_url="https://x.test/A.PDF"),
            _meeting(date="24 Nov 2022", agenda_url="https://x.test/B.PDF"),
        ]
    )
    assert [m.date for m in merged] == ["08 Dec 2022", "24 Nov 2022"]
