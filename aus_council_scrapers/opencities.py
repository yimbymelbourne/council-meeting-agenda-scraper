"""OpenCities meeting listings—the "OC CL Public Meetings" module.

Granicus's OpenCities CMS ships one meetings module, and a council running it
publishes the same three things whatever its theme looks like:

* **A listing page** of ``div.accordion-list-item-container`` rows, ten to a
  page—newest first, except on a separate upcoming-meetings list, which
  runs soonest first. Each row carries the meeting date, the meeting type and
  a ``data-cvid``—and nothing else. There are no document links on it.
* **A document payload per meeting**, from
  ``/OCServiceHandler.axd?url=ocsvc/Public/meetings/documentrenderer&cvid=…``,
  which is the HTML the accordion fetches when a visitor opens a row. Every
  document lives here, so the cost of this platform is about one request per
  meeting, and nothing can bring that down except fetching fewer meetings.
* **A year filter**, which matters because it is what lets production—which
  asks for one year—fetch one year's meetings instead of the whole history.

A subclass supplies the listing URL and two decisions that differ by council
and are verified against it rather than guessed at runtime:

``list_name``
    The listing's internal name, e.g. ``"OC CL Public Meetings"``. With it the
    year filter and pager are plain GETs—
    ``<listing>?dlv_<list name>=(dd_OC%20Year=2026)(pageindex=2)``—which are
    independent of one another and record cleanly. The name is not on the
    page; it shows up in the form's ``action`` after a filter postback, and it
    varies: ``OC CL Public Meetings``, ``OC CL Public2 Meetings``,
    ``OC CL Public Past Meetings``, ``OC CL Public Upcoming Meetings``. A wrong
    name is not an error—the site ignores it and serves the unfiltered first
    page—which is why `_walk_dlv` checks every row's year.

    Leave it ``None`` to drive the ASP.NET form instead (`_walk_postback`),
    which is what ``mornington_peninsula`` was built on and still uses.

``papers_by``
    Where a payload says which file is which. ``"heading"`` for councils that
    group files under ``<div class="meeting-document"><h3>Agenda</h3>`` with
    every link labelled "Download PDF" (Banyule, Kingston, Hobsons Bay,
    Maribyrnong, Melton, Stonnington). ``"link_text"`` for councils that put
    every file in one flat "Related Information" list, so the only label is
    the link's own text (Mornington Peninsula, Frankston, The Hills, Hume).
    Monash files neither way and overrides `papers` itself.

    Two more modes cover themes the first two misread. ``"folder"`` is for
    payloads that group files under ``<div class="meeting-folder"><h3
    class="folder-title">Agenda</h3>``, where each file's own label is a
    ``div.meeting-document-title`` and the folder's heading is the only
    thing that says agenda or minutes (Lake Macquarie, Pyrenees, Queenscliffe
    to mid-2023). ``"search"`` is heading mode for councils whose headings
    put the meeting's name or a date *before* the word, in forms the
    leading-date stripping below cannot take off—"General Meeting Agenda 15
    September 2026" (Gladstone), "17 December 2025 Confirmed Council Meeting
    Minutes" (Central Goldfields), "Ordinary Meeting of Council 26 August
    2026 - Minutes" (Queenscliffe)—so it looks for "agenda" or "minutes"
    anywhere in the heading. It reads folders too, because Queenscliffe's
    payloads of late 2023 mix the two layouts. Both are new rather than
    changes to heading mode, whose start-anchored match is what keeps
    Kingston's "Minutes relating to item 15.2" and Onkaparinga's "Notice of
    adjourned meeting" out.

    Every mode reads the NSW vocabulary too: a "Business Paper" is the agenda,
    and outranks a bare "Agenda" on the same meeting (Snowy Valleys, Bland,
    Broken Hill, Gilgandra); a heading may lead with the meeting's date or
    name ("20 August 2026 - Minutes", "Ordinary Council Meeting - Confirmed
    Minutes"). A link whose href is a bare GUID is rebuilt as a
    ``/files/<guid>/`` URL (Bland, Broken Hill). Further rules are opt-in
    because they infer more: ``label_dates_must_match``,
    ``title_only_agenda``, ``title_heading_agenda`` (a heading that is only
    the meeting's title is its agenda, at Kempsey) and
    ``bound_business_paper``.

Optionally, ``meeting_types``: a pattern a row's meeting type must match before
its payload is fetched. Since each payload is a request, a council listing a
dozen committees should be cut down to Council meetings and planning bodies—
the meetings this project exists to watch.

A council whose layout differs gets hooks rather than a fork:
``extra_listings`` for further lists (a separate upcoming list, a planning
panel's page), ``main_listing`` with ``Listing.filters`` to filter a list by
meeting type, ``Listing.by_year=False`` where the year filter drops meetings,
and ``row_papers`` / ``meeting_name`` where the listing row, not the payload,
says which paper a row is—Blacktown lists a meeting's agenda and its minutes
as two rows of their own.

Optionally, ``page_size``: rows per ``dlv_`` listing page, sent as
``(pagesize=N)``. The meetings module honours it, alongside ``pageindex``,
so a council listing 80 meetings a year is read in one request instead of
nine (Gold Coast and West Torrens, October 2026).
Opt-in, because a subclass whose cassette was recorded without it would ask
for URLs its cassette never saw.

Optionally, ``detail_pages``: for a council whose listing rows carry no
``data-cvid``, only a link to a page per meeting—West Torrens, whose
accordion bodies are inline and say "View full details". The meeting's page
is then its payload, and its URL the record's ``webpage_url``. The renderer is
the cheaper choice wherever rows have a cvid: its payload is a couple of KB,
where a meeting page is the whole themed site (~200 KB) for the same links.

Form control names (``ctl10$ctl00$ctl08`` and so on) are never hard-coded:
they shift by one between councils depending on what else is on the page, so
they are found from what the controls are—the select whose options are page
numbers, the select offering "Any Year", the "Go" button.
"""

from __future__ import annotations

import datetime
import itertools
import json
import re
from dataclasses import dataclass
from typing import Iterator, Optional
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    _merge_split_meetings,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

# The pager's wrapper carries the page count as a class, e.g.
# `seamless-pagination seamless-pagination-count-16`.
_PAGE_COUNT_CLASS = re.compile(r"^seamless-pagination-count-(\d+)$")

# No cachebuster, so each URL is unique per meeting and records/replays
# cleanly. `keywords=` is what the site's own accordion sends.
_RENDERER_PATH = (
    "/OCServiceHandler.axd"
    "?url=ocsvc/Public/meetings/documentrenderer"
    "&keywords="
    "&cvid={cvid}"
)

_YEAR = re.compile(r"\b(\d{4})\b")

# --- what a link or heading is --------------------------------------------

_AGENDA = re.compile(r"\bagendas?\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)

# Papers that mention the agenda or the minutes but are not them: attachment
# books ("Agenda - Supporting Information Attachments", "Agenda - appendices"),
# and the second documents a meeting can grow—an addendum or supplementary
# agenda is real, but storing it as *the* agenda would lose the main paper.
# "Minutes without attachments" is the opposite of an attachment book: it is
# the minutes, beside "Minutes with Attachments" (Cambridge, 25 February 2025).
_NOT_THE_PAPER = re.compile(
    r"\b(?:(?<!without )attachments?|appendi(?:x|ces)|supporting|addendum|supplementary"
    r"|late\s+items?|errata)\b",
    re.IGNORECASE,
)

# A paper that is the agenda or minutes, but an earlier or a reworked version
# of it. Used only when nothing plainer exists, so a meeting holding both
# "Draft Minutes" and "Final Minutes" reports the final ones.
_PROVISIONAL = re.compile(r"\b(?:draft|unconfirmed|amended|revised)\b", re.IGNORECASE)

# Heading mode matches the start of the heading, because the councils that use
# it also title one-off papers with the same words. After the word, a
# separator and a date or qualifier ("Minutes - 25 & 26 May 2026", "Agenda -
# reports") is the plain form. Kingston's 2020 special meetings also put a
# bare qualifier after it—"Agenda 6:30pm", "Minutes Property Matter",
# "Minutes 7pm COVID 19"—and those are the only papers those meetings have,
# so they count too, ranked below a plain heading on the same meeting.
# "Public Minutes" sits beside "Confidential Minutes" at Cambridge (8 April
# 2024); "public" is a qualifier like "final", and "confidential" is not.
# Onkaparinga's panel names itself first—"CAP Agenda 21 March 2024", "CAP
# Minutes 5 May 2022"—so a planning panel's initials may lead. Kempsey's
# minutes are "Signed Minutes - 20 August 2024" and "... - Confirmed Meeting
# Minutes" (2023–2024); "signed", "adopted" and "approved" qualify the
# minutes as "confirmed" does.
_BODY = r"(?:(?:cap|dap|lpp)\s+)?"
_AGENDA_HEADING = re.compile(
    rf"^{_BODY}(?:(?:final|open|public)\s+)?agenda\b", re.IGNORECASE
)
_MINUTES_HEADING = re.compile(
    rf"^{_BODY}(?:(?:un)?confirmed\s+|draft\s+|final\s+|public\s+"
    rf"|signed\s+|adopted\s+|approved\s+)?(?:meeting\s+)?minutes\b",
    re.IGNORECASE,
)
_PLAIN_HEADING = re.compile(
    rf"^{_BODY}(?:(?:final|open|public|(?:un)?confirmed|draft"
    rf"|signed|adopted|approved)\s+)?(?:agenda|minutes)"
    r"(?:$|\s*[-–—:(])",
    re.IGNORECASE,
)

# The agenda with its attachments bound into the same file, which is still the
# agenda: Melton's only agenda heading through 2022 is "Agenda with
# attachments", and Stonnington's 23 November 2020 one is "Council Agenda and
# Attachments". Unlike "Agenda - Supporting Attachments" (Frankston) or
# "Attachments - Part 1 of 2: Main Agenda" (Hobsons Bay), the attachments here
# come *with* the agenda rather than being the paper. Ranked below a plain
# "Agenda" on the same meeting, so a separate agenda would still win.
_WITH_ATTACHMENTS = re.compile(
    r"^agenda\s+(?:with|and|including|plus)\s+attachments$", re.IGNORECASE
)

# A heading for one item's paper rather than the meeting's: Kingston files
# "Minutes relating to item 15.2 - CEO Employment Matters" beside the real
# "Minutes" (June 2026).
_ONE_ITEM = re.compile(r"\brelating\s+to\b|\bitem\s+\d", re.IGNORECASE)

# --- "Business Paper": the NSW word for the agenda -------------------------
#
# NSW councils call the agenda with its officers' reports the business paper,
# and several never use the word "agenda" for it: Broken Hill's
# "2609-Open-Business-Paper-Ordinary-Council-Meeting-held-30-September-
# 2026.pdf", Bland's "Business Paper September 2026", Gilgandra's
# "15 September 2026 - Business Paper", Murrumbidgee's "August 2026 Council
# Meeting - Business Papers" (October 2026). Where a council publishes both,
# the business paper is the one to keep: Snowy Valleys files a short
# "Agenda"—the order of business, about 150 KB—beside a 5 MB "Business
# Paper" holding the reports, so a business paper outranks an agenda on the same meeting.
_BUSINESS_PAPER = re.compile(r"\bbusiness[\s-]+papers?\b", re.IGNORECASE)

# Papers that name the business paper but are not it: "Questions on the
# Business Paper", and Bland's "Business Paper Extra Attachments October
# 2026", an attachment book that "attachments" alone would also exclude but
# whose "extra" is what says so.
_NOT_A_BUSINESS_PAPER = re.compile(
    r"\bquestions?\s+on\b|\bextra\b|\bseparate\b", re.IGNORECASE
)

# The business paper with its attachments bound in, which is still the
# business paper: Central Darling's only paper for a meeting is "18 August
# 2026 Ordinary Central Darling Shire Council Meeting Business Paper with
# attachments" (2026), "Business Paper including attachments" (2021). The
# label has to say the attachments come *with* the paper. Bland's separate
# attachment books are "Business Paper Attachments - August 2025" and
# "Business Paper September 2025 Attachments" (2025), so "business paper"
# and "attachments" in the same label are not enough. Ranked below a plain
# business paper on the same meeting.
#
# A council whose bound-in paper is not labelled that way names its own form
# (`OpenCitiesMeetingsScraper.bound_business_paper`): Central Darling's
# 2025–2026 papers are "Council-Business-Paper-23-June-2026-Attachments.pdf",
# whose first page is the business paper (checked on 23 July 2025's).
_BOUND_BUSINESS_PAPER = re.compile(
    r"\bbusiness[\s-]+papers?(?:[\s-]+[a-z]+){0,2}?[\s-]+"
    r"(?:with|including|incl\.?|plus|and)[\s-]+attachments?\b",
    re.IGNORECASE,
)
_ATTACHMENTS_WORD = re.compile(r"\battachments?\b", re.IGNORECASE)
# "Ordinary-Council-Meeting-Business-paper-22.05.2024-No-Attachments.pdf"
# (Central Darling) is the business paper alone, beside a separate
# attachment book.
_NO_ATTACHMENTS = re.compile(
    r"\b(?:no|without|excluding)[\s-]+attachments?\b", re.IGNORECASE
)

# InfoCouncil's own file codes, for a council that uploads InfoCouncil's
# output under its filename: Central Darling's 4 December 2025 agenda is
# only "CO_20251204_AGN_77_AT.pdf" (AGN agenda, MIN minutes, AT with
# attachments). Uppercase only, as InfoCouncil writes them. ATT (attachments
# alone) and SUP (a supplementary paper) are not the paper. Ranked below a
# labelled paper.
_CODED_AGENDA = re.compile(r"\bAGN\b")
_CODED_MINUTES = re.compile(r"\bMIN\b")
_CODED_NOT_THE_PAPER = re.compile(r"\b(?:ATT|SUP)\b")

# A heading can lead with the meeting's date or name before saying what the
# paper is: Snowy Valleys' "20 August 2026 - Minutes" beside a plain
# "Minutes" on other meetings, Murrumbidgee's "March 2024 Business Paper",
# Kempsey's "Ordinary Council Meeting - Confirmed Minutes" (December 2023)
# and "Ordinary Council Meeting - 13 December 2022 - Minutes". Heading mode
# strips them, however many, before matching.
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_LEADING_DATE = re.compile(
    rf"^(?:\d{{1,2}}(?:st|nd|rd|th)?\s+)?{_MONTH}\s+\d{{4}}\s*(?:[-–—:]\s*)?",
    re.IGNORECASE,
)
_LEADING_MEETING = re.compile(r"^(?:[a-z]+\s+){0,3}meeting\s*[-–—:]\s*", re.IGNORECASE)

# A heading that is only the meeting's title, which is the agenda: Kempsey
# files its agenda under "Ordinary Council Meeting - 20 October 2026" beside
# "Draft Minutes - 15 September 2026" (2022–2026). Its first PDF is the
# agenda; every item's attachments follow it as untitled sections. Ranked
# below a heading that says "Agenda", and taken as the minutes instead when
# its file is named as minutes. Opt-in (`title_heading_agenda`), because
# other councils' short headings ending in "meeting" are not agendas:
# Onkaparinga's "Notice of adjourned meeting", Melton's "Record of Meeting".
# Headings for a recording, a public forum, a notice or a record are titles
# too, and are not papers, even where the rule is on.
_TITLE_HEADING = re.compile(
    rf"^(?:[a-z]+\s+){{0,3}}meeting"
    rf"(?:\s*[-–—:]?\s*(?:\d{{1,2}}(?:st|nd|rd|th)?\s+)?{_MONTH}\s+\d{{4}})?$",
    re.IGNORECASE,
)
_NOT_A_TITLE = re.compile(
    r"\b(?:video|recording|live\s*stream|stream|watch|minutes?|forum|speakers?"
    r"|notices?|records?)\b",
    re.IGNORECASE,
)
_BUSINESS_PAPER_HEADING = re.compile(
    rf"^{_BODY}(?:(?:final|open|public|full)\s+)?business\s+papers?\b", re.IGNORECASE
)


def _business_paper_rank(label: str, bound: Optional[re.Pattern] = None) -> int | None:
    """0 if the label names the meeting's business paper (see
    _BUSINESS_PAPER), 1 if it names the business paper with its attachments
    bound in (see _BOUND_BUSINESS_PAPER; ``bound`` is a council's own form of
    that), None if it is not the business paper."""
    if (
        not _BUSINESS_PAPER.search(label)
        or _MINUTES.search(label)
        or _NOT_A_BUSINESS_PAPER.search(label)
    ):
        return None
    label = _NO_ATTACHMENTS.sub("", label)
    if not _NOT_THE_PAPER.search(label):
        return 0
    bound_in = _BOUND_BUSINESS_PAPER.search(label) or (
        bound is not None and bound.search(label)
    )
    # Excluded only for "attachments", and that is the bound-in form.
    if bound_in and not _NOT_THE_PAPER.search(_ATTACHMENTS_WORD.sub("", label)):
        return 1
    return None


def _heading_kind(heading: str) -> str:
    """The heading with any leading dates and meeting names taken off, which
    is the part that says what the paper is. Kempsey stacks them: "Ordinary
    Council Meeting - 13 December 2022 - Minutes"."""
    core = heading
    while True:
        stripped = _LEADING_MEETING.sub(
            "", _LEADING_DATE.sub("", core, count=1), count=1
        )
        if stripped == core or not stripped:
            return core
        core = stripped


# --- bare-GUID links ---------------------------------------------------------
#
# OpenCities links a file by `/files/<guid>/<filename>`, and the filename is
# cosmetic: the GUID alone picks the file. Now and then an editor's link
# loses everything but the GUID—Broken Hill's 26 August 2026 minutes are
# `href="31b2b004-8ab9-4a31-8ab3-0eb3200d15eb"`, Bland's 20 October 2026
# business paper `href="e02abdf0-…"`—which a browser resolves against the
# page and gets a 403 or 404. Rebuilt as `/files/<guid>/<link text>.pdf`
# both return the PDF (checked 20 October 2026, with any filename).
_GUID_HREF = re.compile(
    r"^/?(?:files/)?([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/?$", re.IGNORECASE
)
# "(PDF, 53MB)", which the theme appends to a link's text.
_SIZE_SUFFIX = re.compile(
    r"\s*\((?:[a-z]{3,4},?\s*)?[\d.]+\s*[kmg]?b\)\s*$", re.IGNORECASE
)


def _pdf_href(anchor) -> str | None:
    """The anchor's href if it is a PDF, rebuilt if it is a bare GUID, else
    None. A bare GUID whose text names another kind of file (an ``.mp3``
    recording) is None; one whose text has no extension at all is taken as a
    PDF, as every one seen so far is."""
    href = anchor["href"].strip()
    if _is_pdf(href):
        return href
    match = _GUID_HREF.match(href)
    if not match:
        return None
    name = _SIZE_SUFFIX.sub("", anchor.get_text(" ", strip=True)).strip()
    extension = re.search(r"\.([a-z0-9]{2,4})$", name, re.IGNORECASE)
    if extension and extension.group(1).lower() != "pdf":
        return None
    if not extension:
        name += ".pdf"
    filename = re.sub(r"[^\w.\-]+", "-", name).strip("-")
    return f"/files/{match.group(1)}/{filename}"


# --- a label that is only the meeting's name -------------------------------
#
# Some agendas are uploaded under a filename that is just the meeting:
# Broken Hill's "2001-Extraordinary-Council-Meeting-13-January-2020.pdf",
# Gilgandra's "15-September-2020-Open.pdf", Central Darling's
# "Ordinary-Council-Meeting-22-March-2023.pdf". Each sits beside a file that
# says "Minutes", so by elimination it is the agenda. That inference is only
# as good as the elimination, so it is opt-in (`title_only_agenda`) and is
# drawn only when the same payload has minutes and nothing else names the
# agenda.
_TITLE_ONLY_WORD = (
    rf"(?:ordinary|extraordinary|special|council|meetings?|open|public|shire"
    rf"|of|the|\d{{1,4}}|{_MONTH}|\d{{1,2}}\.\d{{1,2}}\.\d{{2,4}})"
)
_TITLE_ONLY_LABEL = re.compile(
    rf"^{_TITLE_ONLY_WORD}(?:[\s_.-]+{_TITLE_ONLY_WORD})*(?:\.pdf)?$", re.IGNORECASE
)
_TITLE_ONLY_NEEDS = re.compile(r"\b(?:meetings?|open)\b", re.IGNORECASE)


def _is_title_only(label: str) -> bool:
    name = _SIZE_SUFFIX.sub("", label).strip()
    return bool(_TITLE_ONLY_LABEL.match(name) and _TITLE_ONLY_NEEDS.search(name))


# --- a link dated for another meeting ----------------------------------------
#
# A full date in a label—"held-30-November-2022", "24 November 2021".
_LABEL_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s_.-]+({_MONTH})[\s_.,-]+(\d{{4}})\b",
    re.IGNORECASE,
)


def drop_links_dated_otherwise(
    content: BeautifulSoup, meeting_date: str, listed: set[datetime.date]
) -> list[str]:
    """Remove links whose text dates them to another meeting.

    Broken Hill's payloads sometimes carry another meeting's minutes: the 29
    November 2023 meeting lists "2211-Open-Minutes-of-the-Ordinary-Council-
    Meeting-held-30-November-2022.pdf", and the 11 November 2021
    extraordinary meeting the 24 November 2021 ordinary minutes. Stored as
    this meeting's minutes, they would be a document of the wrong meeting.

    But the same council also mistypes the day: its 18 December 2024 minutes
    are "...-24-December-2024-confirmed.pdf", its 25 August 2021 minutes
    "...-28-August-2021-...", its 27 May 2020 agenda "...-21-May-2020-...",
    and no meeting was held on any of those days. So a date that is not the
    meeting's counts against a link only when it is in another month, or is
    the date of another meeting in `listed` (the listing's own dates). A
    label with no full date says nothing either way and is kept. Returns the
    labels removed, for logging.
    """
    try:
        wanted = parse_date(meeting_date, dayfirst=True).date()
    except (ValueError, OverflowError):
        return []

    def elsewhere(day: datetime.date) -> bool:
        return (day.year, day.month) != (wanted.year, wanted.month) or day in listed

    dropped = []
    for anchor in content.find_all("a", href=True):
        label = _label(anchor.get_text(" ", strip=True))
        dates = set()
        for day, month, year in _LABEL_DATE.findall(label):
            try:
                dates.add(parse_date(f"{day} {month} {year}").date())
            except (ValueError, OverflowError):
                continue
        if dates and wanted not in dates and all(elsewhere(d) for d in dates):
            dropped.append(label)
            anchor.decompose()
    return dropped


def _label(text: str) -> str:
    """A link text or heading, ready to match.

    Underscores become spaces because labels built from filenames use them as
    separators—Frankston's "OM3_-_10_March_2020_Agenda.pdf"—and ``_`` is a
    word character, so ``\\bagenda\\b`` would never match it.
    """
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def _year_of(date_str: str) -> int | None:
    match = _YEAR.search(date_str)
    return int(match.group(1)) if match else None


def _year_filter(year: int) -> str:
    """The ``dlv_`` filter for one year of the listing."""
    return f"(dd_OC%20Year={year})"


def _is_pdf(href: str) -> bool:
    # Skips the livestream links, the Google Maps link and the "Download All"
    # zip, which sit in the same lists as the papers.
    return urlparse(href).path.lower().endswith(".pdf")


@dataclass(frozen=True)
class ListingRow:
    date: str
    meeting_type: str
    cvid: str
    webpage_url: str
    #: The row's own link—the meeting's page—where it has one.
    detail_url: str = ""

    @property
    def key(self) -> str:
        return self.cvid or self.detail_url


# --------------------------------------------------------------------------
# The listing page
# --------------------------------------------------------------------------


def form_state(html: str) -> dict[str, str]:
    """The fields ``form#mainForm`` would submit, as currently rendered.

    Submit buttons are left out so the caller adds exactly the one it wants to
    press. ``__SEAMLESSVIEWSTATE`` matters and is picked up here—the pager
    ignores a post that omits it—and unlike a classic ASP.NET
    ``__VIEWSTATE`` it is a couple of hundred bytes, so carrying it in the
    cassette key costs nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    state: dict[str, str] = {}

    for field in soup.find_all("input"):
        name = field.get("name")
        kind = (field.get("type") or "text").lower()
        if not name or kind in ("submit", "button", "image"):
            continue
        if kind in ("checkbox", "radio") and not field.get("checked"):
            continue
        state[name] = field.get("value", "")

    for select in soup.find_all("select"):
        name = select.get("name")
        if not name:
            continue
        chosen = select.find("option", selected=True) or select.find("option")
        state[name] = (chosen.get("value") if chosen else "") or ""

    return state


def page_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(class_=_PAGE_COUNT_CLASS):
        for class_name in element.get("class", []):
            match = _PAGE_COUNT_CLASS.match(class_name)
            if match:
                return int(match.group(1))
    # No pager at all is what a single page of results looks like.
    return 1


def parse_listing_rows(html: str, webpage_url: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for container in soup.find_all("div", class_="accordion-list-item-container"):
        trigger = container.find("a", class_="accordion-trigger")
        if not trigger:
            continue
        cvid = trigger.get("data-cvid", "").strip()
        href = (trigger.get("href") or "").strip()
        # Some themes put "#" or a javascript: target on the trigger, which is
        # not a meeting page.
        detail_url = (
            urljoin(webpage_url, href)
            if href and not href.startswith(("#", "javascript:"))
            else ""
        )
        date_span = container.find("span", class_="minutes-date")
        type_span = container.find("span", class_="meeting-type")
        date_str = date_span.get_text(strip=True) if date_span else ""
        meeting_type = type_span.get_text(strip=True) if type_span else ""
        if (cvid or detail_url) and date_str:
            rows.append(
                ListingRow(date_str, meeting_type, cvid, webpage_url, detail_url)
            )
    return rows


def filtered_rows(html: str, webpage_url: str) -> list[ListingRow]:
    """The rows the year filter and pager actually apply to.

    Hume puts a "Next Meeting" block (``div.list-meetings-upcoming``) above
    its "Previous Meetings" list (``div.list-meetings-past``), and the next
    meeting is in it on every page of every year—the 2020 filter's pages
    start with 26 October 2026. That row is real and is still collected, but
    it is no evidence about the filter, nor about whether a page predates the
    wanted years. So when a page carries both blocks, the upcoming one is left
    out here. A page holding only an upcoming list—Kingston's and Frankston's
    separate upcoming pages—is that list, and is read whole.
    """
    soup = BeautifulSoup(html, "html.parser")
    pinned = soup.find_all("div", class_="list-meetings-upcoming")
    if not pinned or not soup.find("div", class_="list-meetings-past"):
        return parse_listing_rows(html, webpage_url)
    for block in pinned:
        block.decompose()
    return parse_listing_rows(str(soup), webpage_url)


def _year_select(soup: BeautifulSoup):
    for select in soup.find_all("select"):
        if select.get("name") and select.find(
            "option", string=re.compile(r"^\s*Any Year\s*$", re.IGNORECASE)
        ):
            return select
    # Onkaparinga's filter has no "Any Year" option, only a blank one ahead of
    # the years. A select whose every labelled option is a year is the same
    # control; the pager's select (1..N) never has four-digit labels.
    for select in soup.find_all("select"):
        labels = [o.get_text(strip=True) for o in select.find_all("option")]
        labels = [label for label in labels if label]
        if (
            select.get("name")
            and len(labels) >= 2
            and all(re.fullmatch(r"(?:19|20)\d\d", label) for label in labels)
        ):
            return select
    return None


def offered_years(html: str) -> dict[int, str] | None:
    """The listing's own year filter, as ``{year: option value}``.

    None when the page has no year filter at all, which is a different thing
    from a filter offering nothing in range.
    """
    select = _year_select(BeautifulSoup(html, "html.parser"))
    if select is None:
        return None
    years = {}
    for option in select.find_all("option"):
        label = option.get_text(strip=True)
        if label.isdigit() and len(label) == 4:
            years[int(label)] = option.get("value") or label
    return years


def _pager_controls(soup: BeautifulSoup) -> tuple[str, str, str] | None:
    """``(page select name, Go button name, Go button value)``.

    The page select is the one whose options are the page numbers 1..N. "Go"
    is used rather than "Next": each request is then independent of the last,
    built from page 1's form state. "Next" reads the page number out of the
    state posted to it, so replaying it from a stale state returns the same
    page forever.
    """
    page_select = None
    for select in soup.find_all("select"):
        labels = [o.get_text(strip=True) for o in select.find_all("option")]
        if (
            select.get("name")
            and labels
            and labels[0] == "1"
            and all(label.isdigit() for label in labels)
        ):
            page_select = select["name"]
            break
    go = soup.find(
        "input",
        attrs={"type": "submit", "value": re.compile(r"^\s*Go\s*$", re.IGNORECASE)},
    )
    if not page_select or not go or not go.get("name"):
        return None
    return page_select, go["name"], go.get("value", "Go")


def _search_button(soup: BeautifulSoup, year_select) -> tuple[str, str] | None:
    # The filter's own Search button follows its selects. The site-wide search
    # box near the top of the page has a "Search" button too, so taking the
    # first one on the page would search the website instead.
    button = year_select.find_next("input", attrs={"type": "submit"})
    if not button or not button.get("name"):
        return None
    return button["name"], button.get("value", "")


# --------------------------------------------------------------------------
# One meeting's papers
# --------------------------------------------------------------------------


def _pick(candidates: list[tuple[str, str, int]]) -> str | None:
    """The best-ranked paper: plainly labelled before provisional ("Draft
    Minutes"), then by the candidate's own rank (0 is a plain heading), then
    in listed order."""
    ranked = sorted(
        enumerate(candidates),
        key=lambda c: (bool(_PROVISIONAL.search(c[1][0])), c[1][2], c[0]),
    )
    return ranked[0][1][1] if ranked else None


def papers_by_link_text(
    content: BeautifulSoup,
    base_url: str,
    title_only_agenda: bool = False,
    bound_business_paper: Optional[re.Pattern] = None,
) -> dict[str, str]:
    """Pick the agenda and minutes out of one flat list of files.

    Classification is on the **link text only**, never the href: Mornington
    Peninsula keeps every file under ``/files/assets/.../meetings-amp-minutes/``,
    so matching the URL scores "minutes" against every attachment book.

    Everything else in the list is left alone. It is a long tail—attachment
    books, public notices of cancelled and rescheduled meetings, public
    question time responses, mayoral minutes (singular, so ``\\bminutes\\b``
    passes them by), community meeting flyers—and none of it is the agenda
    or the minutes.
    """
    agendas: list[tuple[str, str, int]] = []
    business: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    for anchor in content.find_all("a", href=True):
        href = _pdf_href(anchor)
        if not href:
            continue
        label = _label(anchor.get_text(" ", strip=True))
        url = urljoin(base_url, href)
        business_rank = _business_paper_rank(label, bound_business_paper)
        if business_rank is not None:
            business.append((label, url, business_rank))
            continue
        if _NOT_THE_PAPER.search(label):
            continue
        if _AGENDA.search(label):
            agendas.append((label, url, 0))
        elif _MINUTES.search(label):
            minutes.append((label, url, 0))
        elif _CODED_NOT_THE_PAPER.search(label):
            continue
        elif _CODED_AGENDA.search(label):
            agendas.append((label, url, 1))
        elif _CODED_MINUTES.search(label):
            minutes.append((label, url, 1))
    agenda = _pick(business) or _pick(agendas)
    if not agenda and title_only_agenda and minutes:
        # See _TITLE_ONLY_LABEL.
        agenda = next(
            (
                urljoin(base_url, href)
                for anchor in content.find_all("a", href=True)
                if (href := _pdf_href(anchor))
                and _is_title_only(_label(anchor.get_text(" ", strip=True)))
            ),
            None,
        )
    return _papers(agenda, _pick(minutes))


def _is_minutes_file(url: str) -> bool:
    """A file whose own name says minutes and not agenda."""
    name = _label(urlparse(url).path.rsplit("/", 1)[-1].replace("-", " "))
    return bool(_MINUTES.search(name)) and not _AGENDA.search(name)


def _in_nested_attachments(anchor, section) -> bool:
    for parent in anchor.parents:
        if parent is section:
            return False
        if parent.name == "div" and "meeting-attachments" in (
            parent.get("class") or []
        ):
            return True
    return False


def papers_by_heading(
    content: BeautifulSoup,
    base_url: str,
    title_heading_agenda: bool = False,
    bound_business_paper: Optional[re.Pattern] = None,
) -> dict[str, str]:
    """Pick the agenda and minutes by the heading each file is filed under.

    Only ``div.meeting-document`` sections are read. The payload's other list,
    ``div.meeting-attachments`` ("Related Information"), holds item appendices
    and, at Kingston, links to *other* meetings' papers—"View minutes of 30
    March 2026 Special Council Meeting" sits on the 22 June 2026 meeting.

    The exception is a payload with no ``meeting-document`` section at all.
    Kingston's 25 July 2022 Council Meeting is one: its agenda and minutes are
    only in the Related Information list, labelled by filename
    ("Public-Agenda-Council-Meeting-25-July-2022.pdf"). With no headings to go
    by, that list is read by link text. The fallback stays that narrow, so a
    meeting that has headings never picks up the cross-meeting links.
    """
    sections = content.find_all("div", class_="meeting-document")
    if not sections:
        related = content.find_all("div", class_="meeting-attachments")
        if not related:
            return {}
        return papers_by_link_text(
            BeautifulSoup("".join(str(div) for div in related), "html.parser"),
            base_url,
            bound_business_paper=bound_business_paper,
        )

    agendas: list[tuple[str, str, int]] = []
    business: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    for section in sections:
        h3 = section.find("h3")
        if not h3:
            continue
        heading = _label(h3.get_text(" ", strip=True))
        # What the paper is, with any leading date or meeting name taken off.
        kind = _heading_kind(heading)
        bound_in = bool(_WITH_ATTACHMENTS.match(kind))
        business_rank = (
            _business_paper_rank(kind, bound_business_paper)
            if _BUSINESS_PAPER_HEADING.match(kind)
            else None
        )
        is_business_paper = business_rank is not None
        not_the_paper = (
            bool(_NOT_THE_PAPER.search(heading))
            and not bound_in
            and not is_business_paper
        )
        if not_the_paper or _ONE_ITEM.search(heading):
            continue
        # The paper is the section's own "Download PDF" link. A section can
        # also nest a Related Information list—Kingston's 22 June 2026 links
        # another meeting's minutes from one—and Hobsons Bay files attachment
        # books under its Agenda heading ("Attachments - Part 1 of 2: Main
        # Agenda", 10 October 2023). So nested lists, and links whose own
        # text says they are not the paper, are passed over rather than
        # trusting link order.
        url = next(
            (
                urljoin(base_url, href)
                for a in section.find_all("a", href=True)
                if (href := _pdf_href(a))
                and not _in_nested_attachments(a, section)
                and not _NOT_THE_PAPER.search(_label(a.get_text(" ", strip=True)))
            ),
            None,
        )
        if not url:
            continue
        rank = 0 if _PLAIN_HEADING.match(kind) and not bound_in else 1
        bare_title = (
            title_heading_agenda
            and not _MINUTES_HEADING.match(kind)
            and not _AGENDA_HEADING.match(kind)
            and not is_business_paper
            and _TITLE_HEADING.match(heading)
            and not _NOT_A_TITLE.search(heading)
        )
        if bare_title:
            # The meeting's bare title (see _TITLE_HEADING). It is the
            # agenda, unless its file says minutes: Kempsey's 15 July 2025
            # files the minutes under "Ordinary Council Meeting - 15 July
            # 2025" and the agenda under "Business Paper - ...".
            if _is_minutes_file(url):
                minutes.append((heading, url, 2))
            else:
                agendas.append((heading, url, 2))
            continue
        names_agenda = is_business_paper or _AGENDA_HEADING.match(kind)
        if names_agenda and _is_minutes_file(url):
            # Filed under the wrong heading: Cambridge's 8 April 2024
            # Special Council Meeting and 20 September 2022 Development
            # Committee put the minutes PDF under "Agenda". Storing it as
            # the agenda would report a document that is not one. The file
            # is still the minutes, so it is a candidate for them, ranked
            # below any heading that says "Minutes": Kempsey's 21 April
            # 2020 files its minutes under a second "Agenda - 21 April 2020"
            # heading and nowhere else.
            minutes.append((heading, url, 3))
            continue
        if is_business_paper:
            business.append((heading, url, business_rank))
        elif _AGENDA_HEADING.match(kind):
            agendas.append((heading, url, rank))
        elif _MINUTES_HEADING.match(kind):
            minutes.append((heading, url, rank))
    return _papers(_pick(business) or _pick(agendas), _pick(minutes))


# --- folder and search modes -------------------------------------------------

# An item's own paper, numbered as the agenda numbers it: Queenscliffe's
# "6.2.2 Unconfirmed Minutes Audit & Risk Committee Meeting on 20 April 2026"
# and "13.1.1 Quarterly Financial Report" sit beside the meeting's minutes.
# One- or two-digit parts only, so a dotted date ("28.4.2026 Ordinary Council
# Meeting Agenda", Wujal Wujal) is not an item number.
_ITEM_NUMBER = re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,3}\.?\s")


def _says(label: str) -> str | None:
    """``"agenda"`` or ``"minutes"`` when the label names exactly one of
    them as a word anywhere, else None. "Agenda and Minutes" is None: it
    says nothing about which this file is."""
    agenda = bool(_AGENDA.search(label))
    minutes = bool(_MINUTES.search(label))
    if agenda == minutes:
        return None
    return "agenda" if agenda else "minutes"


def _file_says(url: str) -> str | None:
    """What the file's own name says it is, as `_says`."""
    name = _label(urlparse(url).path.rsplit("/", 1)[-1].replace("-", " "))
    return _says(name)


def _not_a_paper(label: str) -> bool:
    return bool(
        _NOT_THE_PAPER.search(label)
        or _ONE_ITEM.search(label)
        or _ITEM_NUMBER.match(label)
    )


def _own_title(document) -> str:
    title = document.find("div", class_="meeting-document-title")
    return _label(title.get_text(" ", strip=True)) if title else ""


def _folder_title(folder) -> str:
    heading = folder.find(class_="folder-title")
    if (
        heading is None
        or heading.find_parent("div", class_="meeting-folder") is not folder
    ):
        return ""
    return _label(heading.get_text(" ", strip=True))


@dataclass(frozen=True)
class FolderDocument:
    """One file in a ``div.meeting-folder``: the heading of the folder it
    sits in, its own title, and its href (rebuilt if a bare GUID)."""

    folder: str
    title: str
    href: str


def folder_documents(content: BeautifulSoup) -> list[FolderDocument]:
    """Every file filed in a ``div.meeting-folder``, in payload order.

    The folder is the *nearest* one: Queenscliffe's 8 November 2023 minutes
    sit in a "Minutes" folder inside a "Reports" folder, and its later
    payloads put each item's attachments in an "Attachments" folder inside
    the minutes' own section. A file with no PDF link (Lake Macquarie lists
    "Service Delivery Standing Committee" on 10 August 2020 with nothing to
    download) is left out.
    """
    documents = []
    for document in content.find_all("div", class_="meeting-document"):
        title = document.find("div", class_="meeting-document-title")
        if title is None:
            # A headed section (``<h3>`` and links), which search mode reads.
            continue
        folder = document.find_parent("div", class_="meeting-folder")
        if folder is None:
            continue
        href = next(
            (h for a in document.find_all("a", href=True) if (h := _pdf_href(a))),
            None,
        )
        if href:
            documents.append(
                FolderDocument(_folder_title(folder), _own_title(document), href)
            )
    return documents


def _folder_candidates(
    content: BeautifulSoup,
    base_url: str,
    bound_business_paper: Optional[re.Pattern],
    agendas: list,
    business: list,
    minutes: list,
) -> None:
    """Add each folder file that is an agenda or minutes to the lists.

    The folder's heading says which: "Agenda", "Minutes", or a business
    paper. Folders for anything else—"Attachments", "Questions on items",
    "Reports", Queenscliffe's untitled per-item folders—are passed over.
    Within a folder, a file titled as an attachment book or one item's paper
    is not the paper ("October 2026 Ordinary Meeting Agenda Attachments",
    Pyrenees; "Supplementary Agenda", Lake Macquarie). A title naming the
    folder's kind ranks 0, a title naming nothing (Lake Macquarie's
    "Ordinary Meeting") 1, and a title naming the *other* kind is filed as
    that kind at 2: the title is about this one file, the folder about all
    of them.
    """
    for document in folder_documents(content):
        folder, title = document.folder, document.title
        if _NOT_THE_PAPER.search(folder) or _not_a_paper(title):
            continue
        url = urljoin(base_url, document.href)
        if _BUSINESS_PAPER.search(folder) and not _MINUTES.search(folder):
            rank = _business_paper_rank(title, bound_business_paper)
            if rank is not None:
                business.append((title, url, rank))
                continue
            kind = "agenda"
        else:
            kind = _says(folder)
        if kind is None:
            continue
        titled = _says(title)
        if titled is None or titled == kind:
            target = agendas if kind == "agenda" else minutes
            target.append((title, url, 0 if titled == kind else 1))
        else:
            (agendas if titled == "agenda" else minutes).append((title, url, 2))


def papers_by_folder(
    content: BeautifulSoup,
    base_url: str,
    bound_business_paper: Optional[re.Pattern] = None,
) -> dict[str, str]:
    """Pick the agenda and minutes by the folder each file is filed in.

    See `_folder_candidates`. Lake Macquarie's agenda folder holds
    "Ordinary Meeting", "Information Meeting", "Amended Agenda" and
    "Supplementary Agenda": the supplementary paper is excluded, the amended
    one is provisional and ranks below a plain one, and the rest go in
    payload order, which puts the meeting's own agenda first.
    """
    agendas: list[tuple[str, str, int]] = []
    business: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    _folder_candidates(
        content, base_url, bound_business_paper, agendas, business, minutes
    )
    return _papers(_pick(business) or _pick(agendas), _pick(minutes))


def _section_link(section) -> str | None:
    """A headed section's own paper: its first PDF that is not in a list or
    folder nested inside it and is not labelled as something else."""
    for anchor in section.find_all("a", href=True):
        href = _pdf_href(anchor)
        if not href or _NOT_THE_PAPER.search(_label(anchor.get_text(" ", strip=True))):
            continue
        nested = False
        for parent in anchor.parents:
            if parent is section:
                break
            if parent.name == "div" and {"meeting-attachments", "meeting-folder"} & set(
                parent.get("class") or []
            ):
                nested = True
                break
        if not nested:
            return href
    return None


def papers_by_search(
    content: BeautifulSoup,
    base_url: str,
    bound_business_paper: Optional[re.Pattern] = None,
    related_fills_gaps: bool = False,
    title_heading_agenda: bool = False,
) -> dict[str, str]:
    """Pick the agenda and minutes by searching each heading for the word.

    Each ``div.meeting-document`` section with an ``<h3>`` is classified by
    the one of "agenda" or "minutes" its heading names, wherever in the
    heading it is. A heading naming neither—Queenscliffe's 13 December 2023
    "Ordinary Meeting of Council 13 December 2023"—or both is classified by
    its file's name instead, ranked below a heading that says. A heading
    for an attachment book or one item's paper is not the paper ("Attachments
    to Item 7.4", Central Goldfields; "28.4.2026 Ordinary Council Meeting
    Appendices", Wujal Wujal), nor is one whose file is named as the other
    kind, which is filed as that kind instead (as in heading mode). Notices
    ("Special Budget Meeting Notice 21 July 2026", Gladstone) name neither
    and their files neither, so they drop out.

    Files in ``div.meeting-folder`` folders are read as `papers_by_folder`
    reads them, ranked alongside. A payload with neither falls back to its
    Related Information list by link text, as heading mode does.

    ``title_heading_agenda`` takes a heading that names neither paper, and
    whose file does not either, as the agenda when the heading is the
    meeting's title: Queenscliffe's 12 June 2024 Planning Review Meeting
    files its agenda under "Planning Review Meeting 12 June 2024" as
    ``planning-review-meeting-12-june-2024.pdf`` (its first page says
    "Agenda"). Ranked below any heading that says, and opt-in for the same
    reason as heading mode's rule (see `_TITLE_HEADING`).

    ``related_fills_gaps`` also reads the Related Information list when the
    sections hold only one of the two papers: Central Goldfields files 19
    November 2025's agenda and 23 July 2025's minutes there alone, labelled by
    filename. Opt-in, because at Kingston that list links other meetings'
    papers (see `papers_by_heading`).
    """
    sections = [
        s
        for s in content.find_all("div", class_="meeting-document")
        if s.find("h3") is not None
        and s.find_parent("div", class_="meeting-folder") is None
    ]
    agendas: list[tuple[str, str, int]] = []
    business: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    for section in sections:
        heading = _label(section.find("h3").get_text(" ", strip=True))
        business_rank = (
            _business_paper_rank(heading, bound_business_paper)
            if _BUSINESS_PAPER.search(heading)
            else None
        )
        if business_rank is None and _not_a_paper(heading):
            continue
        href = _section_link(section)
        if not href:
            continue
        url = urljoin(base_url, href)
        filed_as = _file_says(url)
        if business_rank is not None:
            if filed_as == "minutes":
                minutes.append((heading, url, 3))
            else:
                business.append((heading, url, business_rank))
            continue
        says = _says(heading)
        if says is None:
            if filed_as is not None:
                (agendas if filed_as == "agenda" else minutes).append((heading, url, 2))
            elif (
                title_heading_agenda
                and re.search(r"\bmeeting\b", heading, re.IGNORECASE)
                and not _NOT_A_TITLE.search(heading)
            ):
                agendas.append((heading, url, 3))
            continue
        if filed_as is not None and filed_as != says:
            # Filed under the wrong heading; see papers_by_heading.
            (agendas if filed_as == "agenda" else minutes).append((heading, url, 3))
            continue
        (agendas if says == "agenda" else minutes).append((heading, url, 0))
    _folder_candidates(
        content, base_url, bound_business_paper, agendas, business, minutes
    )

    papers = _papers(_pick(business) or _pick(agendas), _pick(minutes))
    has_both = "agenda" in papers and "minutes" in papers
    if (not sections and not papers) or (related_fills_gaps and not has_both):
        related = [
            div
            for div in content.find_all("div", class_="meeting-attachments")
            if div.find_parent("div", class_="meeting-document") is None
        ]
        if related:
            listed = papers_by_link_text(
                BeautifulSoup("".join(str(div) for div in related), "html.parser"),
                base_url,
                bound_business_paper=bound_business_paper,
            )
            for kind, url in listed.items():
                papers.setdefault(kind, url)
            papers = _papers(papers.get("agenda"), papers.get("minutes"))
    return papers


def _papers(agenda: str | None, minutes: str | None) -> dict[str, str]:
    # One file cannot be both. Mornington Peninsula occasionally lists the same
    # PDF twice under two labels—the Cemetery Trust's 21 August 2024 agenda
    # is offered again as that meeting's minutes—and reporting it as minutes
    # would manufacture a document that was never published. The agenda is
    # kept because that is what the file is named.
    if minutes and minutes == agenda:
        minutes = None
    papers = {}
    if agenda:
        papers["agenda"] = agenda
    if minutes:
        papers["minutes"] = minutes
    return papers


def clean_location(location_div) -> str | None:
    """The address text from a ``meeting-address`` div.

    The markup is ``<h3>Location</h3><p>…address… <a>View Map</a></p>``. The
    paragraph holding the map link is the address, and nothing else in the
    div is: councils use it for notices too—"Access via Young Street
    entrance" (Frankston), "DAU meetings are not open to the public" and
    COVID-era livestream notices with no address at all (The Hills). So
    without a map link there is no location, rather than a sentence stored as
    one. That also drops the odd honest "Online only" (Kingston), which is the
    cheaper error.
    """
    address = None
    for paragraph in location_div.find_all("p"):
        if paragraph.find("a", href=re.compile(r"maps\.google\.com")):
            address = paragraph
            break
    if address is None:
        return None

    for anchor in address.find_all("a", href=True):
        if "maps.google.com" in anchor["href"] or re.fullmatch(
            r"view map", anchor.get_text(strip=True), re.IGNORECASE
        ):
            anchor.decompose()

    return re.sub(r"\s+", " ", address.get_text(" ", strip=True)).strip() or None


# --------------------------------------------------------------------------
# The scraper
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    """One listing page to walk. Most councils have one; Kingston and
    Frankston split theirs into past and upcoming meetings, as two lists with
    different names."""

    url: str
    list_name: Optional[str] = None
    #: The years the listing holds, when it is one year's archive page—
    #: Hume keeps 2020 on a page of its own. Such a listing is fetched only
    #: when one of its years is wanted, and only those years are walked, so
    #: its generic year filter (Hume's offers 2016–2027) costs no requests.
    years: Optional[frozenset] = None

    #: Extra ``dlv_`` filters, already encoded—e.g.
    #: ``"(dd_OC%20Meeting%20Type=Minutes%20of%20the%20Ordinary%20Meeting)"``
    #: —applied to every page of this listing, the first included. Needs
    #: ``list_name``.
    filters: str = ""

    #: False for a council whose year filter cannot be trusted. Blacktown's
    #: leaves out most meetings: 2 of the 11 "Minutes of the Ordinary
    #: Meeting" rows its listing shows for 2025, and nothing after 7 October
    #: 2026. Such a listing is paged newest first instead, stopping once a
    #: page reaches back before the earliest wanted year. Needs ``list_name``.
    by_year: bool = True

    #: Raise rather than warn if this listing's first page fails. The main
    #: listing always is; set it on an extra listing that carries papers the
    #: main one does not, as Blacktown's minutes listings do.
    required: bool = False

    def dlv_url(self, extra: str = "") -> str:
        """This listing's URL with its filters, plus ``extra`` (a year or a
        page index). The bare URL when there is nothing to filter by."""
        if not self.list_name or not (self.filters or extra):
            return self.url
        return f"{self.url}?dlv_{quote(self.list_name)}={self.filters}{extra}"


class OpenCitiesMeetingsScraper(BaseScraper):
    #: The listing's internal name for the ``dlv_`` filter URL, or None to
    #: drive the form by postback. See the module docstring.
    list_name: Optional[str] = None

    #: ``"heading"``, ``"link_text"``, ``"folder"`` or ``"search"``—see the
    #: module docstring.
    papers_by: str = "link_text"

    #: In search mode, take a paper the headed sections lack from the
    #: Related Information list, by link text. See `papers_by_search`.
    related_fills_gaps: bool = False

    #: When set, only rows whose meeting type matches are fetched.
    meeting_types: Optional[re.Pattern] = None

    #: With ``years_filter`` set, fetch a dlv listing's first page already
    #: filtered to the newest wanted year. The bare first page is otherwise
    #: fetched only to read the year dropdown, then that year's page is
    #: fetched anyway—a request a listing, every night. The filtered page
    #: carries the same dropdown, offering every year, on Unley, Onkaparinga
    #: and Cambridge (checked October 2026); opt-in because the other
    #: councils have not been checked.
    year_filtered_first_page: bool = False

    #: Rows per ``dlv_`` listing page, or None for the site's own default.
    page_size: Optional[int] = None

    #: Read each meeting's own page instead of the renderer payload.
    detail_pages: bool = False

    #: Ignore a payload's links whose text dates them to another meeting—
    #: another meeting's paper filed on this one (Broken Hill). Opt-in,
    #: because it trusts the dates in a council's labels; see
    #: `drop_links_dated_otherwise`.
    label_dates_must_match: bool = False

    #: In link-text mode, take a PDF labelled only with the meeting's name
    #: and date as the agenda when nothing else names one and the minutes are
    #: there beside it. See `_TITLE_ONLY_LABEL`.
    title_only_agenda: bool = False

    #: In heading mode, take a heading that is only the meeting's title
    #: ("Ordinary Council Meeting - 20 October 2026") as the agenda's, or the
    #: minutes' when its file is named as minutes (Kempsey). See
    #: `_TITLE_HEADING`. In search mode, the same for a title heading whose
    #: file names neither paper (Queenscliffe); see `papers_by_search`.
    title_heading_agenda: bool = False

    #: A council's own label for its business paper with the attachments
    #: bound in, where the label does not say "with attachments"—Central
    #: Darling's "Council-Business-Paper-23-June-2026-Attachments.pdf". See
    #: `_BOUND_BUSINESS_PAPER`.
    bound_business_paper: Optional[re.Pattern] = None

    #: Also keep the rows on the main listing's bare first page that no
    #: year's filter returns. Gilgandra's 20 October 2026 meeting is on the
    #: bare listing with its business paper, but on no year's page (checked
    #: 20 October 2026): a row nobody has tagged with a year yet. The bare
    #: page holds the ten newest rows, which is where a freshly added one
    #: sits. Costs the bare page's request in production, which
    #: ``year_filtered_first_page`` would otherwise save.
    bare_page_rows: bool = False

    def __init__(self, council_name: str, state: str, listing_url: str):
        parts = urlparse(listing_url)
        super().__init__(council_name, state, f"{parts.scheme}://{parts.netloc}")
        self.listing_url = listing_url
        self.webpage_url = listing_url

    # ------------------------------------------------------------------
    # Which listings, which years
    # ------------------------------------------------------------------

    def main_listing(self) -> Listing:
        """The listing whose first page must load. Override to filter it, as
        Blacktown does by meeting type."""
        return Listing(self.listing_url, self.list_name)

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        """Listings besides the main one, e.g. a separate upcoming-meetings
        list. Given the main listing's first page, which is already fetched,
        so a subclass can find a link on it without another request."""
        return []

    def _wanted_years(self) -> set[int]:
        """The years to fetch.

        Production passes one year through ``years_filter``, and that is what
        keeps this platform affordable: payloads are fetched only for meetings
        in the wanted years, and with a ``list_name`` the listing is filtered
        to them too.
        """
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _filtering(self) -> bool:
        return bool(getattr(self, "years_filter", None))

    def _year_dlv(self, year: int) -> str:
        """The ``dlv_`` filter for one year of a listing, with ``page_size``
        when the subclass sets one."""
        size = f"(pagesize={self.page_size})" if self.page_size else ""
        return _year_filter(year) + size

    # ------------------------------------------------------------------
    # Walking a listing
    # ------------------------------------------------------------------

    def _fetch_listing_page(
        self, url: str, required: bool = False, **kwargs
    ) -> str | None:
        """One listing page, or None if it failed and is not ``required``.

        A later page or the upcoming list is tolerated: one unreachable page
        costs ten meetings, and abandoning the run costs all of them. The main
        listing's first page, and each wanted year's first page of it, are
        ``required`` and raise. Swallowing those is how a council blocked from
        the runner (403 from a WAF, a 5xx) "succeeds" with no meetings and is
        counted among the ok councils—see AGENTS.md on ``okCouncils``.
        """
        if required:
            return self.fetcher.fetch_with_requests(url, **kwargs)
        try:
            return self.fetcher.fetch_with_requests(url, **kwargs)
        except Exception as e:
            self.logger.warning(f"Listing page {url} failed: {e}")
            return None

    def _walk_dlv(
        self, listing: Listing, first: str, years: list[int], required: bool
    ) -> Iterator[str]:
        """Yield each page of each wanted year, through the ``dlv_`` GET URL.

        The listing is walked a year at a time even when every year is
        wanted, so a recorded cassette exercises the same requests production
        makes for its one year. Measured on The Hills, Frankston, Kingston and
        Hobsons Bay (October 2026), the per-year listings add up to exactly
        the unfiltered listing—no meeting is filed under the wrong year—and
        so do 2025 and 2026 on Unley and Onkaparinga, and 2026 on Cambridge
        (checked October 2026). Not on
        Blacktown, which is why ``Listing.by_year`` exists.
        """
        prefetched = getattr(self, "_prefetched", {})
        for year in years:
            year_filter = self._year_dlv(year)
            url = listing.dlv_url(year_filter)
            if url in prefetched:
                page_1 = prefetched.pop(url)
            else:
                page_1 = self._fetch_listing_page(url, required)
            if page_1 is None:
                continue
            yield page_1
            if not self._filter_held(page_1, listing, year):
                # The caller keeps this page's rows for the wanted year, but
                # paging an unfiltered listing a year at a time would fetch
                # the whole history once per year.
                continue
            for page in range(2, page_count(page_1) + 1):
                html = self._fetch_listing_page(
                    listing.dlv_url(f"{year_filter}(pageindex={page})")
                )
                if html is not None:
                    yield html

    def _walk_dlv_pages(self, listing: Listing, first: str) -> Iterator[str]:
        """Yield a ``by_year=False`` listing's pages, newest first, until one
        reaches back before the earliest wanted year.

        Production's one-year run therefore reads only the first page or two
        of each listing. A recorded cassette reads them all back to
        EARLIEST_YEAR, which is more listing pages than production makes—but
        the same URLs, so replay exercises the code production runs.
        """
        yield first
        latest = first
        for page in range(2, page_count(first) + 1):
            if self._reaches_before_wanted(latest):
                break
            html = self._fetch_listing_page(listing.dlv_url(f"(pageindex={page})"))
            if html is not None:
                latest = html
                yield html

    def _reaches_before_wanted(self, html: str) -> bool:
        """True once a newest-first page ends before the earliest wanted year:
        every later page is older still. Stopping there rather than at the
        first page wholly older saves a request a listing—Blacktown's
        ordinary agendas for 2026 fit on page 1 beside two from 2025."""
        dates = []
        for row in parse_listing_rows(html, ""):
            try:
                dates.append(parse_date(row.date, fuzzy=True).date())
            except (ValueError, OverflowError):
                continue
        if not dates or dates[0] < dates[-1]:
            return False
        return min(dates).year < min(self._wanted_years())

    def _filter_held(self, html: str, listing: Listing, year: int) -> bool:
        stray = [
            row.date
            for row in filtered_rows(html, listing.url)
            if _year_of(row.date) != year
        ]
        if stray:
            # The site ignores a dlv name it does not know and serves the
            # unfiltered first page, so a council renaming its list shows up
            # here and nowhere else.
            self.logger.warning(
                f"{listing.url}: the {year} filter returned meetings from other "
                f"years ({stray[:3]}); is list_name {listing.list_name!r} still "
                f"right? Only the first page was read."
            )
            return False
        return True

    def _walk_postback(
        self, listing: Listing, first: str, years: list[int], required: bool
    ) -> Iterator[str]:
        """Yield listing pages by driving the ASP.NET form.

        Unfiltered, this is the whole listing paged with "Go"—the listing
        already reaches back to the earliest meeting, so filtering year by
        year would cost the same requests to return a subset. With
        ``years_filter`` it posts the year filter first, then pages within
        that result. Pager posts then go to the filtered page's own form
        ``action``, which carries the filter: posting them to the bare listing
        URL drops it.
        """
        if not self._filtering():
            yield from self._page_postback(listing.url, first)
            return

        offered = offered_years(first) or {}
        soup = BeautifulSoup(first, "html.parser")
        year_select = _year_select(soup)
        search = _search_button(soup, year_select) if year_select else None
        if not year_select or not search:
            self.logger.warning(
                f"{listing.url}: no year filter found on the listing; "
                f"walking the whole listing instead."
            )
            yield from self._page_postback(listing.url, first)
            return

        state = form_state(first)
        for year in years:
            data = {**state, year_select["name"]: offered[year], search[0]: search[1]}
            filtered = self._fetch_listing_page(
                listing.url, required, method="POST", data=data
            )
            if filtered is None:
                continue
            form = BeautifulSoup(filtered, "html.parser").find("form", id="mainForm")
            action = urljoin(listing.url, form.get("action")) if form else listing.url
            yield from self._page_postback(action, filtered)

    def _page_postback(self, url: str, first: str) -> Iterator[str]:
        yield first
        pages = page_count(first)
        if pages < 2:
            return
        controls = _pager_controls(BeautifulSoup(first, "html.parser"))
        if controls is None:
            self.logger.warning(
                f"{url}: {pages} listing pages but no pager controls found; "
                f"only the first page was read."
            )
            return
        page_select, go_name, go_value = controls
        state = form_state(first)
        latest = first
        for page in range(2, pages + 1):
            if self._predates_wanted(latest):
                break
            data = {**state, page_select: str(page), go_name: go_value}
            html = self._fetch_listing_page(url, method="POST", data=data)
            if html is not None:
                latest = html
                yield html

    def _predates_wanted(self, html: str) -> bool:
        """True once a page of a newest-first listing is wholly older than the
        earliest wanted year, so every later page is too.

        Upcoming-meeting lists run the other way—Kingston's starts at the
        next meeting and ends in 2027—so a page in ascending order never
        stops the walk.
        """
        dates = []
        for row in filtered_rows(html, ""):
            try:
                dates.append(parse_date(row.date, fuzzy=True).date())
            except (ValueError, OverflowError):
                continue
        if not dates or dates[0] < dates[-1]:
            return False
        return max(dates).year < min(self._wanted_years())

    def _walk(self, listing: Listing, first: str, required: bool) -> Iterator[str]:
        if listing.list_name and not listing.by_year:
            yield from self._walk_dlv_pages(listing, first)
            return

        offered = offered_years(first)
        if listing.list_name and offered is None:
            # Nothing to filter by, so page through everything the slow way;
            # rows outside the wanted years are dropped by the caller.
            self.logger.warning(
                f"{listing.url}: no year filter on the listing; paging the "
                f"whole listing instead."
            )
            yield from self._page_postback(listing.url, first)
            return

        # Asking for a year the filter does not offer returns nothing, so
        # those requests are skipped. Newest first, matching the listing's own
        # order.
        wanted = self._wanted_years()
        if listing.years:
            wanted = wanted & listing.years
        years = sorted(
            (y for y in offered or {} if y in wanted and y >= EARLIEST_YEAR),
            reverse=True,
        )
        if listing.list_name:
            yield from self._walk_dlv(listing, first, years, required)
        else:
            yield from self._walk_postback(listing, first, years, required)

    def _first_page(self, listing: Listing, required: bool) -> str | None:
        """The page a listing's walk starts from, which is also where its
        year dropdown is read. See ``year_filtered_first_page``."""
        if not (
            self.year_filtered_first_page
            and self._filtering()
            and listing.list_name
            and listing.by_year
        ):
            html = self._fetch_listing_page(listing.dlv_url(), required)
            if html is not None:
                self._bare_pages[listing.dlv_url()] = html
            return html
        wanted = self._wanted_years()
        if listing.years:
            # A one-year archive listing (Hume's 2020 page) is only walked
            # for its own years, so start from the newest of those.
            wanted = wanted & listing.years
        url = listing.dlv_url(self._year_dlv(max(wanted)))
        html = self._fetch_listing_page(url, required)
        if html is not None:
            # _walk_dlv takes this as that year's first page rather than
            # fetching it again.
            self._prefetched[url] = html
        return html

    def _bare_page(self, listing: Listing) -> str | None:
        """The listing's bare first page, fetched only if the walk has not
        already (see ``bare_page_rows``). A failure is a warning: the page
        only adds rows the year filter left out."""
        url = listing.dlv_url()
        if url in self._bare_pages:
            return self._bare_pages[url]
        return self._fetch_listing_page(url)

    def _rows(self) -> list[ListingRow]:
        self._prefetched: dict[str, str] = {}
        self._bare_pages: dict[str, str] = {}
        main = self.main_listing()
        first = self._first_page(main, required=True)

        wanted = self._wanted_years()
        listings = [(main, first)]
        for extra in self.extra_listings(first):
            if extra.years and not extra.years & wanted:
                continue
            extra_first = self._first_page(extra, extra.required)
            if extra_first is not None:
                listings.append((extra, extra_first))

        rows: list[ListingRow] = []
        seen: set[str] = set()
        for listing, listing_first in listings:
            required = listing is main or listing.required
            pages = self._walk(listing, listing_first, required)
            if listing is main and self.bare_page_rows and listing.by_year:
                # After the year pages, so a row they hold keeps its place
                # and the bare page adds only the rows they left out.
                pages = itertools.chain(pages, [self._bare_page(listing)])
            for html in pages:
                if html is None:
                    continue
                for row in parse_listing_rows(html, listing.url):
                    if self.detail_pages and not row.detail_url:
                        continue
                    if not self.detail_pages and not row.cvid:
                        continue
                    if row.key in seen:
                        continue
                    seen.add(row.key)
                    year = _year_of(row.date)
                    if year is None or year < EARLIEST_YEAR or year not in wanted:
                        continue
                    if self.meeting_types and not self.meeting_types.search(
                        row.meeting_type
                    ):
                        continue
                    rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # One meeting
    # ------------------------------------------------------------------

    def fetch_payload(self, row: ListingRow) -> BeautifulSoup | None:
        """The meeting's document payload: the renderer's HTML, or with
        ``detail_pages`` the meeting's own page."""
        if self.detail_pages:
            try:
                html = self.fetcher.fetch_with_requests(row.detail_url)
            except Exception as e:
                self.logger.warning(
                    f"Error fetching meeting page {row.detail_url}: {e}"
                )
                self._payload_failures += 1
                return None
            return BeautifulSoup(html, "html.parser")

        url = self.base_url + _RENDERER_PATH.format(cvid=row.cvid)
        try:
            raw = self.fetcher.fetch_with_requests(url)
        except Exception as e:
            self.logger.warning(f"Error fetching meeting {row.cvid}: {e}")
            self._payload_failures += 1
            return None
        try:
            html = json.loads(raw).get("html", "")
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse meeting JSON for {row.cvid}")
            return None
        return BeautifulSoup(html, "html.parser") if html else None

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        """``{"agenda": url, "minutes": url}``, either or both. An override may
        also return ``"agenda_html"`` for a council whose agenda is a web page
        rather than a PDF (Monash)."""
        if self.papers_by == "heading":
            return papers_by_heading(
                content,
                self.base_url,
                title_heading_agenda=self.title_heading_agenda,
                bound_business_paper=self.bound_business_paper,
            )
        if self.papers_by == "folder":
            return papers_by_folder(
                content, self.base_url, bound_business_paper=self.bound_business_paper
            )
        if self.papers_by == "search":
            return papers_by_search(
                content,
                self.base_url,
                bound_business_paper=self.bound_business_paper,
                related_fills_gaps=self.related_fills_gaps,
                title_heading_agenda=self.title_heading_agenda,
            )
        return papers_by_link_text(
            content,
            self.base_url,
            title_only_agenda=self.title_only_agenda,
            bound_business_paper=self.bound_business_paper,
        )

    def row_papers(self, content: BeautifulSoup, row: ListingRow) -> dict[str, str]:
        """The papers for one listing row. Override when the row itself says
        which paper its payload holds—Blacktown lists a meeting's agenda and
        its minutes as two rows, each with one unlabelled file."""
        return self.papers(content)

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        """The record's name: the listing's meeting type. Override where that
        type is missing or is not a meeting type—Monash names a meeting from
        the payload's opening line, Blacktown's "Minutes of the Ordinary
        Meeting" names a paper, and Unley names a special meeting from its
        paper filenames."""
        return row.meeting_type or self.default_name

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        if self.label_dates_must_match:
            dropped = drop_links_dated_otherwise(
                content, row.date, getattr(self, "_listed_dates", set())
            )
            if dropped:
                self.logger.info(
                    f"{row.date} {row.meeting_type}: passed over links dated for "
                    f"another meeting: {dropped}"
                )
        papers = self.row_papers(content, row)
        agenda_url = papers.get("agenda")
        minutes_url = papers.get("minutes")
        agenda_html_url = papers.get("agenda_html")
        if not agenda_url and not minutes_url and not agenda_html_url:
            # A meeting that was cancelled or rescheduled keeps its listing row
            # and publishes only a notice saying so, and an upcoming meeting
            # has a row long before it has an agenda. Neither is a meeting to
            # report yet. But a payload with PDFs that none of the rules
            # recognise may be a meeting they wrongly reject—Kingston's 30
            # March 2020 and Frankston's 10 March 2020 were dropped that way
            # before anyone noticed—so say which files were passed over.
            labels = [
                _label(a.get_text(" ", strip=True))
                for a in content.find_all("a", href=True)
                if _pdf_href(a)
            ]
            if labels:
                self.logger.warning(
                    f"{row.date} {row.meeting_type}: no agenda or minutes among "
                    f"its {len(labels)} PDFs, so it is skipped: {labels[:6]}"
                )
            return None

        time_value = None
        time_div = content.find("div", class_="meeting-time")
        if time_div:
            # "Time 06:30 PM", or "Time 01:00 PM - 02:00 PM" where a finish
            # time is given too. The regex takes the start.
            raw_time = re.sub(
                r"^\s*Time\b", "", time_div.get_text(" ", strip=True)
            ).strip()
            match = self.time_regex.search(raw_time)
            time_value = match.group() if match else None

        location_div = content.find("div", class_="meeting-address")
        location = clean_location(location_div) if location_div else None

        return ScraperReturn(
            name=self.meeting_name(row, content, papers),
            date=row.date,
            time=time_value,
            webpage_url=row.detail_url if self.detail_pages else row.webpage_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            agenda_html_url=agenda_html_url,
            download_url=agenda_url or minutes_url,
            location=location,
        )

    def build_returns(
        self, content: BeautifulSoup, row: ListingRow
    ) -> list[ScraperReturn]:
        """The records one listing row stands for. Almost always one; an
        override can split a row that holds two meetings' papers
        (Stonnington, 24 October 2022)."""
        record = self.build_return(content, row)
        return [record] if record else []

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        rows = self._rows()
        self.logger.info(f"Found {len(rows)} meeting entries to process")
        # For label_dates_must_match: the days this listing held a meeting.
        self._listed_dates = set()
        for row in rows:
            try:
                self._listed_dates.add(parse_date(row.date, dayfirst=True).date())
            except (ValueError, OverflowError):
                continue

        self._payload_failures = 0
        results: list[ScraperReturn] = []
        for row in rows:
            content = self.fetch_payload(row)
            if content is None:
                continue
            results.extend(self.build_returns(content, row))

        # A meeting can be listed twice, once with its agenda and once with its
        # minutes: Kingston's 13 November 2024 statutory meeting is two rows
        # with two cvids. Complementary rows become one record; rows whose
        # papers conflict are two real meetings and are both kept.
        results = _merge_split_meetings(results)

        if not results and self._payload_failures:
            # Every listed meeting's documents are a request of their own, and
            # those failed: the site is unreachable, not empty. Returning []
            # would report the council as a success with 0 meetings.
            raise RuntimeError(
                f"{self.council_name}: {self._payload_failures} of {len(rows)} "
                f"meeting fetch(es) failed and no meeting was read"
            )
        if not results:
            self.logger.warning(f"No meetings found for {self.council_name}")
        else:
            self.logger.info(f"Found {len(results)} {self.council_name} meetings")

        return results


# --------------------------------------------------------------------------
# A listing read for another scraper
# --------------------------------------------------------------------------


class OpenCitiesArchive(OpenCitiesMeetingsScraper):
    """One OpenCities meeting listing, read on behalf of another scraper.

    For a council whose meetings moved to another platform (Resolve, at
    Burnside and Moreton Bay) and whose older papers, or a body that never
    moved, are still in its OpenCities meetings module. It borrows the
    owner's fetcher, so its requests are made, recorded and replayed as the
    owner's, and returns records in the owner's terms: ISO dates, times as
    "7:00 PM", and the meeting's own page as `webpage_url` where the listing
    row links one.

    `meeting_type` filters the listing itself to one type through the dlv
    URL—Burnside's panel is a page or two a year where the whole listing is
    six. `meeting_types` (a pattern, as on the base class) instead skips rows
    before their payload is fetched. `name(meeting_type, title)` names a
    record from the row's type and the payload's opening line, which is the
    only place some councils say a meeting was special.

    `heading_prefix` is stripped from the front of each paper's heading
    before `papers_by_heading` reads it. Heading mode anchors "Agenda" and
    "Minutes" at the start, and these archives put the body first: "Council
    Agenda - 9 March 2021" (Burnside), "General agenda", "Special Meeting
    agenda" and "9.30am Post-election Meeting - Agenda" (Moreton Bay).
    """

    list_name = "OC CL Public Meetings"
    papers_by = "heading"

    # `read` always sets `years_filter`, so the first page fetched is the
    # newest wanted year's, which carries the year dropdown too.
    year_filtered_first_page = True

    def __init__(
        self,
        owner: BaseScraper,
        listing_url: str,
        name,
        meeting_type: Optional[str] = None,
        meeting_types: Optional[re.Pattern] = None,
        heading_prefix: Optional[re.Pattern] = None,
    ):
        super().__init__(owner.council_name, owner.state, listing_url)
        self.fetcher = owner.fetcher
        self.logger = owner.logger
        self.name = name
        self.meeting_type = meeting_type
        self.meeting_types = meeting_types
        self.heading_prefix = heading_prefix
        self.before: Optional[datetime.date] = None

    def main_listing(self) -> Listing:
        filters = (
            f"(dd_OC%20Meeting%20Type={quote(self.meeting_type)})"
            if self.meeting_type
            else ""
        )
        return Listing(self.listing_url, self.list_name, filters=filters)

    def read(
        self, years: set[int], before: Optional[datetime.date] = None
    ) -> list[ScraperReturn]:
        """The wanted years' meetings, less any on or after `before` (the day
        the council moved them elsewhere). A failed listing raises."""
        self.years_filter = sorted(years)
        self.before = before
        return self.scraper()

    def _rows(self) -> list[ListingRow]:
        # Rows on or after `before` are dropped before their payloads are
        # fetched: those meetings come from the other platform.
        rows = super()._rows()
        if self.before is None:
            return rows
        return [
            row
            for row in rows
            if parse_date(row.date, dayfirst=True).date() < self.before
        ]

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        if self.heading_prefix:
            for heading in content.select("div.meeting-document > h3"):
                text = heading.get_text(" ", strip=True)
                stripped = self.heading_prefix.sub("", text, count=1)
                if stripped != text:
                    heading.string = stripped
        return super().papers(content)

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        title = content.find("p")
        return self.name(
            row.meeting_type, title.get_text(" ", strip=True) if title else ""
        )

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is None:
            return None
        record.date = parse_date(row.date, dayfirst=True).date().isoformat()
        if record.time:
            record.time = parse_date(record.time).strftime("%I:%M %p").lstrip("0")
        record.webpage_url = row.detail_url or row.webpage_url
        return record
