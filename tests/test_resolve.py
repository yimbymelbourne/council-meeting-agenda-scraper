"""What the Resolve cassettes cannot show.

Cassettes are recorded with no year filter, so they prove the full-history
output and nothing about what production fetches when it asks for one year.
That is the whole cost of a Resolve council—one request per meeting in
range—so it is pinned down here against a fetcher that serves only what
the one-year run should need.
"""

import datetime
import json
import logging
import re

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher, ScraperReturn
from aus_council_scrapers.resolve import ResolveScraper

API = "https://api.resolve.red/public/Events"
DOC = "https://example.resolve.red/web/UserControls/DocPreview.aspx"
PDF_REDIRECT = (
    "<html><head><title>Object moved</title></head><body><h2>Object moved to "
    '<a href="https://civicclerkau.blob.core.windows.net/stream/EXAMPLE/'
    'abc.pdf?sv=2015-12-11&amp;sig=x">here</a>.</h2></body></html>'
)


def _event(id_, date, published=True):
    return {
        "id": id_,
        "name": f"Ordinary Council Meeting - {date}",
        "eventDate": f"{date}T18:30:00",
        "agendaId": id_ + 1000,
        "meetingTypeName": "Ordinary Council Meeting",
        "eventLocation": "",
        "isAgendaPublished": published,
        "isEventPublished": True,
    }


def _detail(*files):
    """The detail call's answer for an event holding these documents."""
    fields = {"agenda": "agendaFile", "packet": "packetFile", "minutes": "minutesFile"}
    return json.dumps(
        {
            field: ({"id": 1, "name": "x.pdf"} if kind in files else None)
            for kind, field in fields.items()
        }
    )


def _page(*events):
    return json.dumps(
        {
            "total": len(events),
            "totalPages": 1,
            "currentPage": 1,
            "results": list(events),
        }
    )


class _ServesOnly(Fetcher):
    """Answers the URLs it was given and fails the test on anything else."""

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        if url not in self.responses:
            pytest.fail(f"one-year run fetched {url}")
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def get_selenium_driver(self):
        raise NotImplementedError

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise NotImplementedError


class _Example(ResolveScraper):
    tenant = "example"

    def __init__(self):
        super().__init__("example", "NSW")


class _ExampleWithUnpublished(_Example):
    include_unpublished = True


def _one_year_run(fetcher, cls=_Example):
    scraper = cls()
    scraper.fetcher = fetcher
    scraper.years_filter = [2026]
    with clock.frozen("2026-10-19"):
        return scraper.scraper()


PAST_2026 = f"{API}?type=past&startDate=2026-01-01&endDate=2026-12-31&page=1"
FUTURE = f"{API}?type=future&page=1"


def test_one_year_fetches_that_year_and_one_detail_per_published_meeting():
    """Production passes one year. The listing must be bounded to it, and the
    per-meeting detail call spent only on that year's published meetings: an
    unpublished one would 404, and the 'future' list's next-year events are
    out of range."""
    with_packet, agenda_only = _event(1, "2026-08-04"), _event(2, "2026-09-22")
    nothing_filed, upcoming = _event(3, "2026-09-29"), _event(4, "2026-10-27")
    unpublished = _event(5, "2026-11-24", published=False)
    next_year = _event(6, "2027-02-02")
    fetcher = _ServesOnly(
        {
            PAST_2026: _page(
                unpublished, upcoming, nothing_filed, agenda_only, with_packet
            ),
            FUTURE: _page(unpublished, upcoming, next_year),
            f"{API}/1": _detail("agenda", "packet", "minutes"),
            f"{API}/2": _detail("agenda", "minutes"),
            f"{API}/3": _detail(),
            f"{API}/4": _detail("packet"),
        }
    )

    results = _one_year_run(fetcher)

    # The packet is the agenda when there is one; a meeting with no
    # documents filed is not a meeting record.
    assert [(r.date, r.agenda_url, r.minutes_url) for r in results] == [
        ("2026-08-04", f"{DOC}?aoid=1001&p=1", f"{DOC}?aoid=1001&m=1"),
        ("2026-09-22", f"{DOC}?aoid=1002", f"{DOC}?aoid=1002&m=1"),
        ("2026-10-27", f"{DOC}?aoid=1004&p=1", None),
    ]
    assert len(fetcher.requested) == 6


def test_unpublished_past_meetings_are_probed_only_where_the_tenant_shows_them():
    """For a tenant whose public portal lists unpublished events, a past one
    is kept if DocPreview serves it. Upcoming ones are drafts, and are never
    asked for."""
    past = _event(1, "2026-03-30", published=False)
    upcoming = _event(2, "2026-11-24", published=False)
    no_file = PDF_REDIRECT.replace("Object moved", "No file")
    fetcher = _ServesOnly(
        {
            PAST_2026: _page(upcoming, past),
            FUTURE: _page(upcoming),
            f"{DOC}?aoid=1001&p=1": no_file,
            f"{DOC}?aoid=1001": PDF_REDIRECT,
            f"{DOC}?aoid=1001&m=1": PDF_REDIRECT,
        }
    )

    results = _one_year_run(fetcher, _ExampleWithUnpublished)

    assert [(r.date, r.agenda_url, r.minutes_url) for r in results] == [
        ("2026-03-30", f"{DOC}?aoid=1001", f"{DOC}?aoid=1001&m=1"),
    ]

    # Without the flag the same listing costs nothing beyond itself.
    fetcher.requested.clear()
    assert _one_year_run(fetcher) == []
    assert fetcher.requested == [PAST_2026, FUTURE]


def test_a_failed_listing_fails_the_council_but_a_failed_future_query_does_not():
    """A council blocked from the runner must not look like one with no
    meetings: production counts an empty list as a council that worked, which
    is how InfoCouncil's DEBUG-level swallow hid bayside_nsw. The extra
    'future' query adds nothing the ranged listing lacks, so it may fail."""
    blocked = _ServesOnly({PAST_2026: ConnectionError("reset"), FUTURE: _page()})
    with pytest.raises(RuntimeError, match="could not read Resolve listing"):
        _one_year_run(blocked)

    meeting = _event(1, "2026-08-04")
    flaky_future = _ServesOnly(
        {
            PAST_2026: _page(meeting),
            FUTURE: ConnectionError("reset"),
            f"{API}/1": _detail("packet", "minutes"),
        }
    )
    assert [r.date for r in _one_year_run(flaky_future)] == ["2026-08-04"]


def test_a_new_council_term_does_not_drop_meetings_from_an_anchored_type():
    """Tenants re-create their types each term ("Council Meeting 2024-2028"),
    and SA councils go to the polls in November 2026. A subclass anchors its
    pattern on the type's name, so the term must not be part of what it sees,
    or every meeting after the election silently drops out."""

    class Anchored(_Example):
        meeting_types = re.compile(r"^Ordinary Council Meeting$")

    next_term = _event(1, "2026-11-24")
    next_term["meetingTypeName"] = "Ordinary Council Meeting 2026-2030"
    fetcher = _ServesOnly(
        {
            PAST_2026: _page(next_term),
            FUTURE: _page(),
            f"{API}/1": _detail("agenda"),
        }
    )

    results = _one_year_run(fetcher, Anchored)

    assert [(r.date, r.name) for r in results] == [
        ("2026-11-24", "Ordinary Council Meeting")
    ]


class _MovedMidYear(_Example):
    """A council that moved to Resolve on 22 June 2026 and keeps its earlier
    meetings elsewhere; the tenant also holds copies of some of them."""

    resolve_from = datetime.date(2026, 6, 22)
    archive_error = None
    asked_for = None

    def other_meetings(self, wanted):
        type(self).asked_for = sorted(wanted)
        if self.archive_error:
            raise self.archive_error
        return [
            ScraperReturn(
                name="Council Meeting",
                date="2026-03-23",
                time=None,
                webpage_url="https://example.nsw.gov.au/meetings/2026",
                agenda_url="https://example.nsw.gov.au/2026-03-23-agenda.pdf",
            )
        ]


FROM_MOVE = f"{API}?type=past&startDate=2026-06-22&endDate=2026-12-31&page=1"


def test_a_council_that_moved_mid_year_reads_each_source_for_its_own_part():
    """In the year of the move, the listing starts at the move, so the
    tenant's copies of earlier meetings cost neither listing pages nor
    detail calls; those meetings come from the other source instead."""
    copy_of_archived = _event(1, "2026-03-23")
    after_move = _event(2, "2026-07-27")
    fetcher = _ServesOnly(
        {
            FROM_MOVE: _page(after_move, copy_of_archived),
            FUTURE: _page(),
            f"{API}/2": _detail("packet", "minutes"),
        }
    )

    results = _one_year_run(fetcher, _MovedMidYear)

    assert [(r.date, r.agenda_url) for r in results] == [
        ("2026-03-23", "https://example.nsw.gov.au/2026-03-23-agenda.pdf"),
        ("2026-07-27", f"{DOC}?aoid=1002&p=1"),
    ]
    assert _MovedMidYear.asked_for == [2026]
    assert f"{API}/1" not in fetcher.requested


def test_a_failed_second_source_fails_the_council_only_when_nothing_else_came_back(
    caplog,
):
    """The archive failing must not discard what Resolve returned, and must
    not hide behind an empty Resolve year either: then it was the only
    source, and its failure is the council's."""

    class ArchiveDown(_MovedMidYear):
        archive_error = ConnectionError("reset")

    with_resolve = _ServesOnly(
        {
            FROM_MOVE: _page(_event(2, "2026-07-27")),
            FUTURE: _page(),
            f"{API}/2": _detail("agenda"),
        }
    )
    with caplog.at_level(logging.WARNING):
        assert [r.date for r in _one_year_run(with_resolve, ArchiveDown)] == [
            "2026-07-27"
        ]
    assert any("other source, which failed" in r.message for r in caplog.records)

    nothing_on_resolve = _ServesOnly({FROM_MOVE: _page(), FUTURE: _page()})
    with pytest.raises(ConnectionError):
        _one_year_run(nothing_on_resolve, ArchiveDown)


def test_a_cancelled_meeting_is_dropped_without_asking_for_its_documents():
    """A cancelled meeting's packet is the notice of cancellation (Mount
    Barker, 16 September 2026), so it is not a meeting with an agenda, and
    learning that should cost nothing."""
    held = _event(1, "2026-08-19")
    cancelled = _event(2, "2026-09-16")
    cancelled["name"] = "Cancelled - Council Assessment Panel 16 September 2026"
    fetcher = _ServesOnly(
        {
            PAST_2026: _page(cancelled, held),
            FUTURE: _page(),
            f"{API}/1": _detail("packet", "minutes"),
        }
    )

    results = _one_year_run(fetcher)

    assert [r.date for r in results] == ["2026-08-19"]
    assert f"{API}/2" not in fetcher.requested
