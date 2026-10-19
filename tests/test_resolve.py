"""What the Resolve cassettes cannot show.

Cassettes are recorded with no year filter, so they prove the full-history
output and nothing about what production fetches when it asks for one year.
That is the whole cost of a Resolve council—one request per meeting in
range—so it is pinned down here against a fetcher that serves only what
the one-year run should need.
"""

import json
import logging

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
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


def test_a_failed_listing_is_reported_not_swallowed(caplog):
    """A council blocked from the runner must not look like one with no
    meetings: InfoCouncil's DEBUG-level swallow hid exactly that."""
    fetcher = _ServesOnly(
        {
            PAST_2026: ConnectionError("reset"),
            FUTURE: _page(),
        }
    )

    with caplog.at_level(logging.WARNING):
        assert _one_year_run(fetcher) == []

    assert any(
        "could not read Resolve listing" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )
