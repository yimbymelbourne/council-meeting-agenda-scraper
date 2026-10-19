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

Form control names (``ctl10$ctl00$ctl08`` and so on) are never hard-coded:
they shift by one between councils depending on what else is on the page, so
they are found from what the controls are—the select whose options are page
numbers, the select offering "Any Year", the "Go" button.
"""

from __future__ import annotations

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
# Minutes 5 May 2022"—so a planning panel's initials may lead.
_BODY = r"(?:(?:cap|dap|lpp)\s+)?"
_AGENDA_HEADING = re.compile(
    rf"^{_BODY}(?:(?:final|open|public)\s+)?agenda\b", re.IGNORECASE
)
_MINUTES_HEADING = re.compile(
    rf"^{_BODY}(?:(?:un)?confirmed\s+|draft\s+|final\s+|public\s+)?minutes\b",
    re.IGNORECASE,
)
_PLAIN_HEADING = re.compile(
    rf"^{_BODY}(?:(?:final|open|public|(?:un)?confirmed|draft)\s+)?(?:agenda|minutes)"
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
        date_span = container.find("span", class_="minutes-date")
        type_span = container.find("span", class_="meeting-type")
        date_str = date_span.get_text(strip=True) if date_span else ""
        meeting_type = type_span.get_text(strip=True) if type_span else ""
        if cvid and date_str:
            rows.append(ListingRow(date_str, meeting_type, cvid, webpage_url))
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


def papers_by_link_text(content: BeautifulSoup, base_url: str) -> dict[str, str]:
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
    minutes: list[tuple[str, str, int]] = []
    for anchor in content.find_all("a", href=True):
        href = anchor["href"].strip()
        if not _is_pdf(href):
            continue
        label = _label(anchor.get_text(" ", strip=True))
        if _NOT_THE_PAPER.search(label):
            continue
        url = urljoin(base_url, href)
        if _AGENDA.search(label):
            agendas.append((label, url, 0))
        elif _MINUTES.search(label):
            minutes.append((label, url, 0))
    return _papers(_pick(agendas), _pick(minutes))


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


def papers_by_heading(content: BeautifulSoup, base_url: str) -> dict[str, str]:
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
        )

    agendas: list[tuple[str, str, int]] = []
    minutes: list[tuple[str, str, int]] = []
    for section in sections:
        h3 = section.find("h3")
        if not h3:
            continue
        heading = _label(h3.get_text(" ", strip=True))
        bound_in = bool(_WITH_ATTACHMENTS.match(heading))
        not_the_paper = bool(_NOT_THE_PAPER.search(heading)) and not bound_in
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
                urljoin(base_url, a["href"].strip())
                for a in section.find_all("a", href=True)
                if _is_pdf(a["href"].strip())
                and not _in_nested_attachments(a, section)
                and not _NOT_THE_PAPER.search(_label(a.get_text(" ", strip=True)))
            ),
            None,
        )
        if not url:
            continue
        rank = 0 if _PLAIN_HEADING.match(heading) and not bound_in else 1
        if _AGENDA_HEADING.match(heading):
            if _is_minutes_file(url):
                # Filed under the wrong heading: Cambridge's 8 April 2024
                # Special Council Meeting and 20 September 2022 Development
                # Committee put the minutes PDF under "Agenda". Storing it as
                # the agenda would report a document that is not one.
                continue
            agendas.append((heading, url, rank))
        elif _MINUTES_HEADING.match(heading):
            minutes.append((heading, url, rank))
    return _papers(_pick(agendas), _pick(minutes))


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

    #: ``"heading"`` or ``"link_text"``—see the module docstring.
    papers_by: str = "link_text"

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
            year_filter = _year_filter(year)
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
            return self._fetch_listing_page(listing.dlv_url(), required)
        wanted = self._wanted_years()
        if listing.years:
            # A one-year archive listing (Hume's 2020 page) is only walked
            # for its own years, so start from the newest of those.
            wanted = wanted & listing.years
        url = listing.dlv_url(_year_filter(max(wanted)))
        html = self._fetch_listing_page(url, required)
        if html is not None:
            # _walk_dlv takes this as that year's first page rather than
            # fetching it again.
            self._prefetched[url] = html
        return html

    def _rows(self) -> list[ListingRow]:
        self._prefetched: dict[str, str] = {}
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
            for html in self._walk(listing, listing_first, required):
                for row in parse_listing_rows(html, listing.url):
                    if row.cvid in seen:
                        continue
                    seen.add(row.cvid)
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
        """The meeting's document payload. Override for a council whose papers
        sit on a page per meeting instead of behind the renderer."""
        url = self.base_url + _RENDERER_PATH.format(cvid=row.cvid)
        try:
            raw = self.fetcher.fetch_with_requests(url)
        except Exception as e:
            self.logger.warning(f"Error fetching meeting {row.cvid}: {e}")
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
            return papers_by_heading(content, self.base_url)
        return papers_by_link_text(content, self.base_url)

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
                if _is_pdf(a["href"].strip())
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
            webpage_url=row.webpage_url,
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

        if not results:
            self.logger.warning(f"No meetings found for {self.council_name}")
        else:
            self.logger.info(f"Found {len(results)} {self.council_name} meetings")

        return results
