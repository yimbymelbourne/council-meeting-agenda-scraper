"""Meeting dates read from a paper's own first page (`pdf_dates`).

The PDFs are built here with pymupdf, so nothing is fetched from a council.
Fetching goes through a real `DefaultFetcher` against a local HTTP server
that honours, or ignores, Range requests the way council hosts do.
"""

from __future__ import annotations

import datetime
import http.server
import random
import re
import string
import threading

import fitz
import pytest
import requests

from aus_council_scrapers.base import DefaultFetcher
from aus_council_scrapers.pdf_dates import (
    PDF_HEAD_BYTES,
    NotAPdf,
    PdfGone,
    PdfText,
    PdfTooLarge,
    find_meeting_date,
    meeting_date_from_pdf,
    partial_pdf_text,
    pdf_text,
)
from tests.cassette import CassetteMiss, PlaybackFetcher, RecordingFetcher

COVER = "BUSINESS PAPER ORDINARY MEETING to be held Wednesday 21 January 2026"


def _pdf(
    cover: str = COVER,
    *,
    filler_pages: int = 0,
    cover_last: bool = False,
    linear: bool = False,
) -> bytes:
    """A PDF whose first page says `cover`, padded with incompressible pages.

    `cover_last` adds the cover after the filler, so its objects sit at the
    end of the file, as an Acrobat-assembled business paper's do.
    """
    rng = random.Random(1)
    doc = fitz.open()

    def add_cover(at: int) -> None:
        page = doc.new_page(at)
        page.insert_textbox(fitz.Rect(72, 72, 520, 400), cover, fontsize=14)

    if not cover_last:
        add_cover(-1)
    for _ in range(filler_pages):
        page = doc.new_page()
        for line in range(60):
            text = "".join(rng.choice(string.ascii_letters) for _ in range(120))
            page.insert_text((20, 20 + line * 12), text, fontsize=6)
    if cover_last:
        add_cover(0)
    return doc.tobytes(garbage=0, deflate=False, linear=linear)


# --- finding the date --------------------------------------------------------


@pytest.mark.parametrize(
    "text, year, month, expected",
    [
        (COVER, 2026, 1, datetime.date(2026, 1, 21)),
        # Ordinals, capitals, no space, and a year some PDFs space out.
        ("ON THE 15THOctober, 2026", 2026, 10, datetime.date(2026, 10, 15)),
        (
            "ORDINARY MEETING MINUTES Thursday 22nd January 2 02 6 .",
            2026,
            1,
            datetime.date(2026, 1, 22),
        ),
        ("HELD ... ON THE 23 RD JUNE 2022", 2022, 6, datetime.date(2022, 6, 23)),
        # A day whose digits are spaced out is not read as its last digit:
        # McKinlay's "1 5 th July 202 5" is the 15th, not the 5th, and
        # Yalgoo's "F riday 2 9th July 202 2" the 29th, not the 9th.
        ("ORDINARY MEETING HELD AT JULIA CREEK 1 5 th July 202 5", 2025, 7, None),
        ("will be held on F riday 2 9th July 202 2", 2022, 7, None),
        # A signed date is not the meeting's, even when it is the only one.
        ("STEPHEN GASH CHIEF EXECUTIVE OFFICER 2 October 2020", 2020, 10, None),
        # A meeting held over two days is dated from the first.
        (
            "ORDINARY COUNCIL MEETING MINUTES 30-31 August 2023",
            2023,
            8,
            datetime.date(2023, 8, 30),
        ),
        (
            "RATIFIED MINUTES Ordinary Meeting - 15th and 16th November 2021 "
            "Monday 15th November, 12:04pm - 5:00pm Tuesday 16th November, 9:00am",
            2021,
            11,
            datetime.date(2021, 11, 15),
        ),
        ("MINUTES 25 \ufffd 26 May 2023", 2023, 5, datetime.date(2023, 5, 25)),
        # An item number or a reporting period is not a two-day meeting.
        (
            "AGENDA Item 17.5 - 20 November 2025 Meeting Date: 20 November 2025",
            2025,
            11,
            datetime.date(2025, 11, 20),
        ),
        ("Accounts paid 1 - 31 May 2023", 2023, 5, datetime.date(2023, 5, 31)),
        # "and" joins two days only after an ordinal.
        ("Items 3 and 4 May 2023", 2023, 5, datetime.date(2023, 5, 4)),
        # Nor does it leave the signature's date as the only one in the month.
        (
            "will be held on F riday 2 9th July 202 2 in the Council Chambers. "
            "CHIEF EXECUTIVE OFFICER 25th July 202 2",
            2022,
            7,
            None,
        ),
        ("Wednesday, January 21, 2026", 2026, 1, datetime.date(2026, 1, 21)),
        ("Meeting date: 21/01/2026", 2026, 1, datetime.date(2026, 1, 21)),
        # A date in another month is not this meeting's.
        ("to be held Wednesday 18 February 2026", 2026, 1, None),
        # 2 January 2025 was a Thursday: a misread "22", not evidence.
        ("Wednesday, 2 January 2025", 2025, 1, None),
        # The title's date wins over the meetings the minutes confirm.
        (
            "MINUTES OF THE ORDINARY MEETING HELD IN THE COUNCIL CHAMBERS ON THE "
            "23 RD JUNE 2022. Confirmation of the minutes of the Extraordinary "
            "Meeting held on 7 June 2022 and the workshop held 3 June 2022",
            2022,
            6,
            datetime.date(2022, 6, 23),
        ),
        # Two days, neither in a title, neither confirmed: no guess.
        (
            "x " * 300 + "Report dated 5 January 2026. Inspection on 12 January 2026.",
            2026,
            1,
            None,
        ),
        # Past the title, a weekday still singles one out.
        (
            "x " * 300
            + "Report dated 5 January 2026. Meeting Wednesday 21 January 2026.",
            2026,
            1,
            datetime.date(2026, 1, 21),
        ),
        ("", 2026, 1, None),
    ],
)
def test_find_meeting_date(text, year, month, expected):
    assert find_meeting_date(text, year, month) == expected


# --- reading a PDF -------------------------------------------------------------


def test_text_comes_from_the_first_pages_only():
    data = _pdf(filler_pages=2)
    assert "21 January 2026" in pdf_text(data, pages=1)
    assert len(pdf_text(data, pages=2)) > len(pdf_text(data, pages=1))


def test_first_bytes_give_the_first_page_when_it_is_written_first():
    data = _pdf(filler_pages=40)
    assert len(data) > PDF_HEAD_BYTES
    assert "21 January 2026" in partial_pdf_text(data[:PDF_HEAD_BYTES], len(data))


def test_first_bytes_give_nothing_when_the_cover_is_at_the_end():
    data = _pdf(filler_pages=40, cover_last=True)
    assert partial_pdf_text(data[:PDF_HEAD_BYTES], len(data)) == ""


def test_linearised_first_page_without_its_page_tree():
    data = _pdf(filler_pages=40, cover_last=True, linear=True)
    # Point the catalog at a page tree that is not there, as when the tree
    # lies past the first bytes (Coolamon's minutes).
    head = re.sub(
        rb"/Pages (\d+) 0 R",
        lambda m: b"/Pages " + b"9" * len(m.group(1)) + b" 0 R",
        data[:PDF_HEAD_BYTES],
    )
    assert fitz.open(stream=head, filetype="pdf").page_count == 0
    assert "21 January 2026" in partial_pdf_text(head, len(data))
    # A file edited after it was linearised may have a new first page.
    assert partial_pdf_text(head, len(data) + 100) == ""


# --- fetching -------------------------------------------------------------------


class _Server:
    """Serves fixed bodies by path, honouring Range unless told not to."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.statuses: dict[str, int] = {}
        self.ignore_range = False
        self.requests: list[tuple[str, str | None]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = server.files.get(self.path)
                rng = self.headers.get("Range")
                server.requests.append((self.path, rng))
                if self.path in server.statuses:
                    self.send_error(server.statuses[self.path])
                    return
                if body is None:
                    self.send_error(404)
                    return
                start, end, status = 0, len(body) - 1, 200
                if rng and not server.ignore_range:
                    first, _, last = rng.removeprefix("bytes=").partition("-")
                    start, end, status = int(first), min(int(last), len(body) - 1), 206
                self.send_response(status)
                if status == 206:
                    self.send_header(
                        "Content-Range", f"bytes {start}-{end}/{len(body)}"
                    )
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                try:
                    self.wfile.write(body[start : end + 1])
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client stopped reading, as it should

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}{path}"


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.httpd.shutdown()


@pytest.fixture
def fetcher():
    return DefaultFetcher(fetch_delay=0)


def test_whole_small_file_in_one_range_request(server, fetcher):
    server.files["/a.pdf"] = _pdf()
    found = fetcher.fetch_pdf_text(server.url("/a.pdf"))
    assert "21 January 2026" in found.text and found.complete
    assert server.requests == [("/a.pdf", f"bytes=0-{PDF_HEAD_BYTES - 1}")]


@pytest.mark.parametrize("ignore_range", [False, True])
def test_large_file_read_only_as_far_as_its_first_page(server, fetcher, ignore_range):
    server.files["/big.pdf"] = data = _pdf(filler_pages=40)
    server.ignore_range = ignore_range
    found = fetcher.fetch_pdf_text(server.url("/big.pdf"))
    assert "21 January 2026" in found.text
    assert not found.complete
    assert found.bytes_read == PDF_HEAD_BYTES < len(data)
    assert len(server.requests) == 1


def test_cover_at_the_end_fetches_the_whole_file(server, fetcher):
    server.files["/end.pdf"] = data = _pdf(filler_pages=40, cover_last=True)
    found = fetcher.fetch_pdf_text(server.url("/end.pdf"))
    assert "21 January 2026" in found.text and found.complete
    assert found.bytes_read == PDF_HEAD_BYTES + len(data)
    assert [r for _, r in server.requests] == [f"bytes=0-{PDF_HEAD_BYTES - 1}", None]


def test_too_large_to_download_whole(server, fetcher):
    server.files["/end.pdf"] = _pdf(filler_pages=40, cover_last=True)
    with pytest.raises(PdfTooLarge):
        fetcher.fetch_pdf_text(server.url("/end.pdf"), full_limit=PDF_HEAD_BYTES)
    assert len(server.requests) == 1


def test_not_a_pdf(server, fetcher):
    server.files["/page.pdf"] = b"<html>Page not found</html>"
    with pytest.raises(NotAPdf):
        fetcher.fetch_pdf_text(server.url("/page.pdf"))


@pytest.mark.parametrize("status", [404, 410])
def test_dead_link_is_left_out_not_a_failure(server, fetcher, status):
    # A council page that links a deleted file must not fail the council
    # every night: the paper is gone, so its meeting is left out and logged.
    server.statuses["/gone.pdf"] = status
    with pytest.raises(PdfGone):
        fetcher.fetch_pdf_text(server.url("/gone.pdf"))
    assert meeting_date_from_pdf(fetcher, server.url("/gone.pdf"), 2026, 1) is None


def test_server_error_still_fails_the_council(server, fetcher):
    # 501 is not retried, so the test does not wait out a backoff.
    server.statuses["/broken.pdf"] = 501
    with pytest.raises(requests.HTTPError):
        meeting_date_from_pdf(fetcher, server.url("/broken.pdf"), 2026, 1)


def test_fetch_bytes_is_not_decoded(server, fetcher):
    server.files["/a.pdf"] = data = _pdf()
    assert fetcher.fetch_bytes(server.url("/a.pdf")) == data
    assert fetcher.fetch_bytes(server.url("/a.pdf"), max_bytes=100) == data[:100]


def test_cassette_replays_bytes_text_and_failures(server, fetcher):
    server.files["/a.pdf"] = data = _pdf()
    server.files["/end.pdf"] = _pdf(filler_pages=40, cover_last=True)
    recorder = RecordingFetcher(fetcher)
    text = recorder.fetch_pdf_text(server.url("/a.pdf"))
    head = recorder.fetch_bytes(server.url("/a.pdf"), max_bytes=100)
    with pytest.raises(PdfTooLarge):
        recorder.fetch_pdf_text(server.url("/end.pdf"), full_limit=PDF_HEAD_BYTES)
    server.statuses["/gone.pdf"] = 404
    with pytest.raises(PdfGone):
        recorder.fetch_pdf_text(server.url("/gone.pdf"))

    playback = PlaybackFetcher(recorder.replay_data)
    assert playback.fetch_pdf_text(server.url("/a.pdf")) == text
    assert (
        playback.fetch_bytes(server.url("/a.pdf"), max_bytes=100) == head == data[:100]
    )
    with pytest.raises(PdfTooLarge):
        playback.fetch_pdf_text(server.url("/end.pdf"), full_limit=PDF_HEAD_BYTES)
    with pytest.raises(PdfGone):
        playback.fetch_pdf_text(server.url("/gone.pdf"))
    # A raised size limit could change the outcome, so it is not replayed
    # from a recording made under the old one.
    with pytest.raises(CassetteMiss):
        playback.fetch_pdf_text(server.url("/end.pdf"))


class _Papers:
    """Serves PdfText by URL and whether the whole file was asked for."""

    def __init__(self, texts):
        self.texts = texts
        self.calls = []

    def fetch_pdf_text(self, url, pages=1, partial=True, full_limit=None):
        self.calls.append(partial)
        found = self.texts[partial]
        if isinstance(found, Exception):
            raise found
        return found


def test_whole_file_read_when_its_first_bytes_have_no_date():
    papers = _Papers(
        {
            True: PdfText("BUSINESS PAPER ORDINARY", complete=False, bytes_read=1),
            False: PdfText(COVER, complete=True, bytes_read=2),
        }
    )
    assert meeting_date_from_pdf(papers, "u", 2026, 1) == datetime.date(2026, 1, 21)
    assert papers.calls == [True, False]


def test_unreadable_paper_is_no_date():
    papers = _Papers({True: PdfTooLarge("too big")})
    assert meeting_date_from_pdf(papers, "u", 2026, 1) is None
