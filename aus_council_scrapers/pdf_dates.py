"""Meeting dates read from the PDF itself.

Some councils label their papers by month only—"MEETING 2026 January
Business Paper", "October 2026 Minutes"—and give the day nowhere on the
page. The paper's own first page does: "BUSINESS PAPER ORDINARY MEETING
Thursday 22nd January 2026", "MINUTES OF THE ORDINARY MEETING ... HELD ...
ON THE 15 OCTOBER 2026". This module reads that page and finds the date.

Use it only where the listing gives the month and year and nothing gives
the day, and only for meetings in the years being scraped: each paper read
costs one or two requests a night. The listing's month and year bound the
answer, and anything ambiguous is None, never a guess.

How a page is read, cheapest first (`read_pdf_text`):

1. The first `PDF_HEAD_BYTES` (256 KB) through an HTTP Range request. A
   server that ignores Range is read only that far and the connection
   closed. Many PDFs put their first page there: Word writes pages in
   order, and a "fast web view" (linearised) file puts page one and the
   objects it needs first. MuPDF repairs the truncated file; a page tree it
   can rebuild gives the real first page. That tree is the file's first
   revision: a later edit appended at the end cannot be seen from here,
   and only the month check guards against one that changed page one.
2. A linearised file whose first-page section fits but whose page tree is
   further on: the linearisation dictionary names page one's object, and a
   one-page tree is built around it. Only when the file has not been edited
   since it was linearised (its stated length is the real one): here an
   edit can be seen, so a file that has one is not trusted. Coolamon's
   signed minutes all have one, which is why they are read whole.
3. Otherwise the whole file, if it is no larger than `full_limit`. Acrobat
   puts a business paper's cover, added last, at the end of the file
   (Warren), and a scanned set of minutes has no text at all.

Text is taken from MuPDF's text trace, the glyphs as drawn, not from
`get_text`: on Carpentaria's covers every glyph reports the same origin, and
`get_text` then drops the second of two identical letters as a fake-bold
copy, so "22 JANUARY" reads "2 JANUARY".
"""

from __future__ import annotations

import calendar
import datetime
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

import fitz

# MuPDF prints a line to stderr for every object a truncated file is
# missing, which is every partial read. The failures that matter surface as
# exceptions or as no text.
fitz.TOOLS.mupdf_display_errors(False)

PDF_HEAD_BYTES = 256 * 1024
# Above this a paper whose first page is not in its first bytes is not
# downloaded. Business papers run to 68 MB (Carpentaria), and one a night is
# already more than a council's listing pages put together.
PDF_FULL_LIMIT = 8 * 1024 * 1024

_logger = logging.getLogger(__name__)


class PdfUnavailable(Exception):
    """The paper's text could not be had within the limits."""


class NotAPdf(PdfUnavailable):
    """The URL answered with something that is not a PDF."""


class PdfTooLarge(PdfUnavailable):
    """The first page was not in the first bytes, and the file is too big."""


class PdfGone(PdfUnavailable):
    """The URL answered 404 or 410: the council's own page links a dead file.

    A dead link is a fact about the council's site, not a passing fault, so
    its meeting is left out and logged like any unreadable paper rather
    than failing the council every night. Timeouts and 5xx errors are not
    this: they still fail the council, so a bad night is never mistaken
    for a short list.
    """


@dataclass(frozen=True)
class PdfText:
    """The text of a paper's first pages, and what it cost to get.

    ``complete`` is False when the text came from the first bytes alone, so
    a caller that finds no date in it can ask for the whole file.
    ``bytes_read`` counts every request made for it.
    """

    text: str
    complete: bool
    bytes_read: int

    def to_record(self) -> dict:
        return {
            "text": self.text,
            "complete": self.complete,
            "bytes_read": self.bytes_read,
        }

    @staticmethod
    def from_record(record: dict) -> "PdfText":
        return PdfText(record["text"], record["complete"], record["bytes_read"])


# --- reading a PDF ---------------------------------------------------------


def is_pdf(data: bytes) -> bool:
    # The header may follow up to 1 KB of junk (a BOM, an HTTP stub).
    return b"%PDF-" in data[:1024]


def _spans_text(spans) -> str:
    out: list[str] = []
    last = None  # (baseline y, right edge x, font size)
    for span in spans:
        chars = [c for c in span.get("chars") or () if c[0] > 0]
        if not chars:
            continue
        x0, _, x1, _ = span["bbox"]
        size = span.get("size") or 10
        y = chars[0][2][1]
        if last is not None:
            same_line = abs(y - last[0]) < 0.5 * max(size, last[2])
            touching = abs(x0 - last[1]) < 0.1 * max(size, last[2])
            if not (same_line and touching):
                out.append(" ")
        # One span can run over several lines (a wrapped text box). Only a
        # change of line is read inside it: some PDFs give every glyph of a
        # span the same origin, so horizontal positions say nothing.
        line_y = y
        for c in chars:
            if abs(c[2][1] - line_y) > 0.5 * size:
                out.append(" ")
                line_y = c[2][1]
            out.append(chr(c[0]))
        last = (line_y, x1, size)
    return "".join(out)


def page_text(page: "fitz.Page") -> str:
    """A page's text, glyph by glyph as it was drawn.

    Spans that continue on the same line with no gap are joined; anything
    else is separated by a space. Stroked text is left out when the page
    has any other: Warren draws every heading twice, filled and then
    stroked, which read together gives "Thurs Thursday day 22nd 22nd".
    """
    trace = page.get_texttrace()
    text = _spans_text(s for s in trace if s.get("type") != 1)
    return text if text.strip() else _spans_text(trace)


def _first_pages_text(doc: "fitz.Document", pages: int) -> str:
    texts = []
    for number in range(min(pages, doc.page_count)):
        try:
            texts.append(page_text(doc[number]))
        except Exception as e:  # a page whose objects are missing
            _logger.debug(f"page {number + 1} unreadable: {e}")
            break
    return "\n".join(texts)


def pdf_text(data: bytes, pages: int = 1) -> str:
    """The text of the first `pages` pages of a whole PDF file."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise NotAPdf(f"not a readable PDF: {e}") from e
    return _first_pages_text(doc, pages)


_LINEARISED = re.compile(rb"<<\s*/Linearized\s[^>]*>>")


def _linearised_first_page(head: bytes, total: Optional[int]) -> str:
    """Page one of a linearised file from its first-page section alone."""
    m = _LINEARISED.search(head[:4096])
    if not m or total is None:
        return ""
    entries = dict(re.findall(rb"/([LOE])\s+(\d+)", m.group(0)))
    try:
        length, first_page, end = (int(entries[k]) for k in (b"L", b"O", b"E"))
    except KeyError:
        return ""
    if length != total or end > len(head):
        # Edited after it was linearised, or the section is cut short.
        return ""
    try:
        doc = fitz.open(stream=head, filetype="pdf")
        catalog = doc.pdf_catalog()
        tree = doc.get_new_xref()
        doc.update_object(tree, f"<</Type/Pages/Kids[{first_page} 0 R]/Count 1>>")
        doc.xref_set_key(first_page, "Parent", f"{tree} 0 R")
        if catalog > 0:
            doc.xref_set_key(catalog, "Pages", f"{tree} 0 R")
        rebuilt = fitz.open(stream=doc.tobytes(), filetype="pdf")
        return _first_pages_text(rebuilt, 1)
    except Exception as e:
        _logger.debug(f"linearised first page unreadable: {e}")
        return ""


def partial_pdf_text(head: bytes, total: Optional[int], pages: int = 1) -> str:
    """The first pages' text from the first bytes of a file, or "".

    `total` is the whole file's length when the server said it.
    """
    try:
        doc = fitz.open(stream=head, filetype="pdf")
        if doc.page_count:
            text = _first_pages_text(doc, pages)
            if text.strip():
                return text
    except Exception as e:
        _logger.debug(f"partial PDF unreadable: {e}")
    return _linearised_first_page(head, total)


# get(url, max_bytes, limit) -> (body, whole file's length or None). With
# max_bytes it returns at most that many bytes; with limit it raises
# PdfTooLarge rather than read past it.
BodyGetter = Callable[
    [str, Optional[int], Optional[int]], "tuple[bytes, Optional[int]]"
]


def read_pdf_text(
    get: BodyGetter,
    url: str,
    pages: int = 1,
    partial: bool = True,
    head_bytes: int = PDF_HEAD_BYTES,
    full_limit: int = PDF_FULL_LIMIT,
) -> PdfText:
    """The text of a paper's first pages, read as cheaply as it can be."""
    spent = 0
    total = None
    if partial:
        head, total = get(url, head_bytes, None)
        spent += len(head)
        if not is_pdf(head):
            raise NotAPdf(f"{url} is not a PDF")
        if total is not None and len(head) >= total:
            return PdfText(pdf_text(head, pages), True, spent)
        text = partial_pdf_text(head, total, pages)
        if not text.strip() and total is None:
            # No length: a CDN fetching the file from its origin for the
            # first time answers the Range request with a 200 and no
            # Content-Length (Carpentaria's Akamai, 26 Oct 2026). The second
            # request is served from its cache, with the length that a
            # linearised file is checked against.
            head, total = get(url, head_bytes, None)
            spent += len(head)
            if total is not None and len(head) >= total:
                return PdfText(pdf_text(head, pages), True, spent)
            text = partial_pdf_text(head, total, pages)
        if text.strip():
            return PdfText(text, False, spent)
    if total is not None and total > full_limit:
        raise PdfTooLarge(
            f"{url}: first page not in the first {head_bytes} bytes, and the "
            f"file is {total} bytes (limit {full_limit})"
        )
    body, _ = get(url, None, full_limit)
    spent += len(body)
    if not is_pdf(body):
        raise NotAPdf(f"{url} is not a PDF")
    return PdfText(pdf_text(body, pages), True, spent)


# --- finding the date --------------------------------------------------------

_MONTH = (
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?![a-z])"
)
# "Thursday", "Thurs", and "Thurs day" as one PDF splits it.
_WEEKDAY = (
    r"(?P<weekday>mon|tue|tues|wed|wednes|thu|thur|thurs|fri|sat|satur|sun)"
    r"(?:\s?day)?\b\.?"
)
_DAY = r"(?<!\d)(?P<day>[0-3]?\d)\s*(?:st|nd|rd|th)?"
# Four digits, which some PDFs space out: "2 02 6".
_YEAR = r"(?P<year>(?:\d\s?){3}\d)(?!\d)"

_DATES = [
    # "Thursday 22nd January 2026", "the 16TH JULY, 2020", "15THOctober, 2026",
    # "21st day of January 2026".
    re.compile(
        rf"(?:{_WEEKDAY}[\s,]+)?(?:the\s+)?{_DAY}[\s,.-]*(?:day\s+of\s+|of\s+)?"
        rf"{_MONTH}\.?[\s,.-]*{_YEAR}",
        re.IGNORECASE,
    ),
    # "Wednesday, January 21, 2026".
    re.compile(
        rf"(?:{_WEEKDAY}[\s,]+)?{_MONTH}\.?\s+{_DAY}(?!\d)[\s,]*{_YEAR}",
        re.IGNORECASE,
    ),
    # "21/01/2026", "21.01.2026": day first, as Australian papers write it.
    re.compile(
        rf"(?:{_WEEKDAY}[\s,]+)?(?<!\d)(?P<day>\d{{1,2}})[./](?P<month>\d{{1,2}})"
        r"[./](?P<year>20\d{2})(?!\d)",
        re.IGNORECASE,
    ),
]

_MONTH_NUMBERS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
_WEEKDAY_NUMBERS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

# Phrases that put a date on the meeting itself rather than on a report,
# a notice or the print run: "to be held on", "held in the Council Chambers
# ... on the 15 October", "Meeting of Council ... commencing".
_ANCHOR = re.compile(
    r"\b(?:to\s+be\s+held|will\s+be\s+held|held|meeting\s+of|commenc\w*|convened)\b",
    re.IGNORECASE,
)
_ANCHOR_WINDOW = 120


@dataclass(frozen=True)
class _Candidate:
    date: datetime.date
    start: int  # where in the text it begins
    weekday_checked: bool  # a weekday was written beside it and agrees
    anchored: bool


def _candidates(text: str) -> list[_Candidate]:
    found = []
    for pattern in _DATES:
        for m in pattern.finditer(text):
            month = m["month"]
            month = int(month) if month.isdigit() else _MONTH_NUMBERS[month[:3].lower()]
            try:
                date = datetime.date(
                    int(re.sub(r"\s", "", m["year"])), month, int(m["day"])
                )
            except ValueError:
                continue
            weekday = m["weekday"]
            if weekday:
                if _WEEKDAY_NUMBERS[weekday[:3].lower()] != date.weekday():
                    # "Wednesday, 2 January 2025" was a Thursday: a misread
                    # or a typo, and either way not evidence.
                    continue
            before = text[max(0, m.start() - _ANCHOR_WINDOW) : m.start()]
            found.append(
                _Candidate(date, m.start(), bool(weekday), bool(_ANCHOR.search(before)))
            )
    # The patterns run one after another; the text's own order is what
    # "first" means.
    return sorted(found, key=lambda c: c.start)


# How far into a page its title runs, in characters once whitespace is
# collapsed. Covers and minutes headings put the meeting date here.
_TITLE_CHARS = 400


def find_meeting_date(text: str, year: int, month: int) -> Optional[datetime.date]:
    """The meeting date a paper's text gives, in the month the listing gives.

    Only a date in `year` and `month` is accepted, in this order:

    1. The only such day in the text.
    2. The first such date, if it is in the page's title (its first
       `_TITLE_CHARS` characters) and a weekday beside it agrees, a phrase
       like "held" or "to be held" introduces it, or it is given twice.
       Coolamon's minutes open "... HELD IN THE COUNCIL CHAMBERS, COOLAMON
       ON THE 23 RD JUNE 2022" and then list the 3 and 7 June meetings
       whose minutes they confirm.
    3. The only day a weekday confirms.

    Otherwise None: a business paper also dates its reports and committee
    meetings in the same month, and a guess would publish a wrong date.
    """
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    in_month = [
        c for c in _candidates(text) if (c.date.year, c.date.month) == (year, month)
    ]
    days = {c.date for c in in_month}
    if len(days) == 1:
        return days.pop()
    if not in_month:
        return None
    first = in_month[0]
    if first.start < _TITLE_CHARS and (
        first.weekday_checked
        or first.anchored
        or sum(c.date == first.date for c in in_month) > 1
    ):
        return first.date
    confirmed = {c.date for c in in_month if c.weekday_checked}
    if len(confirmed) == 1:
        return confirmed.pop()
    return None


def meeting_date_from_pdf(
    fetcher,
    url: str,
    year: int,
    month: int,
    *,
    pages: int = 1,
    full_limit: int = PDF_FULL_LIMIT,
    logger: Optional[logging.Logger] = None,
) -> Optional[datetime.date]:
    """The meeting date on the first pages of the paper at `url`, or None.

    Reads the first bytes first, and the whole file (within `full_limit`)
    only when those gave text but no date. A paper that cannot be read is
    logged and is None: the caller leaves its meeting out, or tries the
    meeting's other paper.
    """
    log = logger or _logger
    try:
        found = fetcher.fetch_pdf_text(url, pages=pages, full_limit=full_limit)
        date = find_meeting_date(found.text, year, month)
        if date is None and not found.complete:
            found = fetcher.fetch_pdf_text(
                url, pages=pages, partial=False, full_limit=full_limit
            )
            date = find_meeting_date(found.text, year, month)
    except PdfGone as e:
        log.warning(f"dead link, left out: {e}")
        return None
    except PdfUnavailable as e:
        log.info(f"cannot read {url}: {e}")
        return None
    if date is None:
        start = re.sub(r"\s+", " ", found.text)[:160]
        log.info(
            f"{url} gives no single day in {calendar.month_name[month]} {year}: "
            f"{start!r}"
        )
    return date


def meeting_date_from_papers(
    fetcher,
    urls,
    year: int,
    month: int,
    *,
    pages: int = 1,
    full_limit: int = PDF_FULL_LIMIT,
    logger: Optional[logging.Logger] = None,
) -> Optional[datetime.date]:
    """The date from the first of a meeting's papers that gives one.

    List the papers cheapest first: small minutes before a business paper
    whose cover is at the end of a large file. The rest are not fetched
    once one gives the date.
    """
    for url in urls:
        if not url:
            continue
        date = meeting_date_from_pdf(
            fetcher, url, year, month, pages=pages, full_limit=full_limit, logger=logger
        )
        if date:
            return date
    return None
