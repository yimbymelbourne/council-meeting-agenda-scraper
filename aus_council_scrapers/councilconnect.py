"""Councils on CouncilConnect, Market Creations Agency's WA council CMS.

CouncilConnect is ASP.NET WebForms. Its meetings module answers on the same
paths on every site that runs it:

    /council-meetings/past/<year>                  every type, one year
    /council-meetings/<type>/past/<year>           one meeting type, one year
    /council-meetings/<type>/<slug>/<id>           one meeting
    /council-meetings/                             upcoming meetings

A year listing shows ten meetings a page. Further pages are not links but
`__doPostBack` calls on the `dpMeetings` DataPager, so paging means posting
the page's own form back with `__EVENTTARGET` set to the pager control. A GET
with a page parameter returns page one again, quietly.

Sites come in two shapes, and a subclass says which:

- **Documents on the meeting page** (Cottesloe, and the default). The listing
  carries only a link per meeting, so each meeting costs a request. That is
  what dominates the bill, so `meeting_types` exists to limit a council to its
  Council meetings and planning bodies when its committees would otherwise
  push one production year past ~20 requests.
- **Documents on the listing** (`inline_documents = True`, East Fremantle).
  Each summary carries a `ul.meeting-documents` with the PDFs, so a year costs
  one request per ten meetings and no meeting page is fetched. The listing's
  own PDF links carry a version that moves whenever the meeting is edited, so
  the version-free address the meeting page would give is emitted instead
  (`_stable_document_url`). What the listing does not give is a meeting's
  time or location; those are only on the meeting page.

Upcoming meetings are not on the year listings at all—they move there once
the date passes—so the upcoming page is read as well.
"""

from __future__ import annotations

import datetime
import difflib
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.utils import requote_uri
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# One type's year listing: /council-meetings/<type>/past/<year>.
_TYPE_LISTING_PATH = re.compile(
    r"^/council-meetings/(?P<type>[a-z0-9-]+)/past/\d{4}/?$"
)

# A meeting's own page: /council-meetings/<type>/<slug>/<id>. Listing and
# per-type paths have "past" or no numeric id, so the trailing id is what
# tells a meeting apart from navigation. A type slug can keep the brackets of
# its name: Albany files its Ordinary meetings under
# "ordinary-council-meeting-(ocm)".
_MEETING_PATH = re.compile(
    r"^/council-meetings/(?P<type>[a-z0-9()-]+)/[^/]+/(?P<id>\d+)/?$"
)

# The listing writes US-order dates ("Tuesday, December 16, 2025 - 06:00 PM"),
# which the project's DATE_REGEX—day before month—does not match.
_LONG_DATE = re.compile(
    r"(?P<date>(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4})"
    r"(?:\s*-\s*(?P<time>\d{1,2}:\d{2}\s*[AP]M))?",
    re.IGNORECASE,
)
# The upcoming page's buttons: "Tue 27 Oct 2026".
_SHORT_DATE = re.compile(r"\b\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\b")
# Or, where the button is undated, the link title: "... - 22/10/2026".
_TITLE_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_BUTTON_TIME = re.compile(r"\b\d{1,2}:\d{2}\s*[AP]M\b", re.IGNORECASE)

# A meeting page groups its documents under headings: "Agenda", "Minutes",
# "Minutes (Confirmed)", "Attachment", and now and then something vaguer
# ("Downloads", "Document"). The grouping is trusted where it is specific.
# Cottesloe files committees' minutes ("10.2.2 Unconfirmed Minutes - Audit
# Committee") among an Ordinary meeting's attachments, so an attachment group
# is never read; but it once put a meeting's own minutes under "Downloads",
# so a vague group falls back to reading each link's label.
_AGENDA_GROUP = re.compile(r"agenda", re.IGNORECASE)
_MINUTES_GROUP = re.compile(r"minut", re.IGNORECASE)
_ATTACHMENT_GROUP = re.compile(r"attach", re.IGNORECASE)

# Matched against link text and filename together. Minutes are matched on the
# stem alone because Cottesloe's are typo'd—"unconfirrmed-minutes",
# "Ordinary Council Neeting"—and "minut" survives every variant seen.
# Leonora shortens it to "MINS" ("Confirmed MINS OCM 16 July 2024").
_MINUTES = re.compile(r"minut|\bmins\b", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
# Typed every which way: York's "Uncomfirmed Minutes" (26 August 2025),
# Moora's "Unconfimed Minutes".
_UNCONFIRMED = re.compile(r"un-?co[nm]fi?r|unconfim", re.IGNORECASE)
_CONFIRMED = re.compile(r"confirm", re.IGNORECASE)
# Papers that ride along with a meeting but are not its agenda or minutes:
# attachments, late items, supplementary agendas, and individual reports
# ("Item 11.1 - Notice of Motion", "13.7 Attachment 1 ..."). Cottesloe also
# files the agenda of the week-earlier Agenda Forum—a councillor briefing,
# not the meeting—under a meeting's "Agenda" heading until the real agenda
# replaces it.
#
# East Fremantle also lists papers tabled at a meeting ("OCM Agenda 150322
# Report 14.4 Tabled Documents") and single reports ("... Report No 14.1.1
# Attach 3") beside the agenda, both named after it.
#
# A leading item number ("10.2.2 ...") marks a single report, but a leading
# dotted date does not: Northam labels every agenda and minutes
# "2025.01.22 - AGENDA - Ordinary Council Meeting - PUBLIC", which the item
# rule alone threw away whole. It does not always pad the day and month
# ("28.1.2026 - AGENDA", "2026.1.28 - MINUTES", 28 January 2026), so a dotted
# run with a four-digit year at either end is a date. Dundas numbers its
# appendices ("App1_ Unconfirmed Minutes - 17 June 2025 OCM", the previous
# meeting's minutes) and files them beside the meeting's own papers.
#
# Nannup files the earlier meetings' minutes that an agenda asks Council to
# receive among that agenda's papers, numbered as agenda items: "Att 5.1 -
# 28 July 2022 OCM Minutes", "Agenda Item 5.3 - Minutes 27 June 2024
# Ordinary Council Meeting", "Attatchment 11.13.3 Shire of Bridgetown
# Minutes ..." (25 August 2022, 25 July 2024, 28 August 2025). Each sits
# before the meeting's own minutes on the page and would be taken for them.
_NOT_THE_MEETINGS = re.compile(
    r"attach|attatch|\blate\b|supplement|addend|presentation|notice.of.motion"
    r"|forum|tabled|\breport\s+(?:no\.?\s*)?\d"
    r"|^\s*item\b"
    r"|^\s*(?!\d{4}\.\d{1,2}\.\d{1,2}\b|\d{1,2}\.\d{1,2}\.\d{4}\b)\d+(?:\.\d+)+"
    r"|^\s*app(?:endix)?\s*\d"
    r"|^\s*att\.?\s*\d|^\s*agenda\s+item\b",
    re.IGNORECASE,
)
# The same test without "attach", for a filename whose link label already
# says it is the agenda or minutes. East Fremantle uploads whole packets as
# "TPC-AGENDA-100221-with-all-attachments.pdf" and
# "Special-Electors-Meeting-150922-Minutes-and-Attachments.pdf"—the meeting's
# only agenda or minutes, which the full test would throw away. A label that
# is about an attachment ("OCM Agenda Item 13.4 Attach 1") is still caught by
# the label test, and a forum or late-item file is still caught here.
_NOT_THE_MEETINGS_FILE = re.compile(
    r"\blate\b|supplement|addend|presentation|notice.of.motion|forum|tabled",
    re.IGNORECASE,
)

# Bodies whose papers a council files on another meeting's page: Westonia's
# Audit Committee agenda and minutes sit on the Ordinary meeting's page
# ("0325 Audit Agenda March 2025"), Moora puts its Briefing Session and Audit
# Committee agendas in an Ordinary meeting's "Agendas" group, and York adds
# an "Agenda Briefing Record" beside the agenda. Which document won used to
# depend on the order the council uploaded them. A document naming one of
# these is another body's unless the meeting's own name says it is that body.
# Westonia files its electors' meeting papers on an Ordinary meeting's page
# too ("0226 Agenda Annual General Meeting of Electors 2026").
_OTHER_BODY = re.compile(r"briefing|audit|committee|electors", re.IGNORECASE)

# Headings that say nothing a meeting type does not say better.
_GENERIC_HEADINGS = {"council meeting", "meeting", "meeting details"}

_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# Strips "16 December 2025 - ", "7 July - " and "- 12 November 2025" from a
# heading, leaving the meeting's name—and "21st October, 2025" (Leonora),
# whose comma used to leave ", 2025" behind in the name.
# The weekday is matched as a whole word, or "Swearing in Ceremony 25 October
# 2023" loses "mony" as if it were "Monday" (Mundaring).
_HEADING_DATE = re.compile(
    rf"(?:\b{_WEEKDAY}\s*)?\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b(?:,?\s+\d{{4}})?",
    re.IGNORECASE,
)

# A document that bundles its attachments, or says it leaves them out, as
# opposed to being one. Nedlands labels its minutes "Council Meeting -
# MINUTES - 25 February 2025 PUBLIC (Excluding Attachments)", which without
# the "exclud" form would be read as an attachment and dropped. York writes
# the "and" as an ampersand ("OCM Agenda & Attachments 25 May 2021"), and
# Nannup shortens it: "Agenda & Attachment" (9 April 2020), "20 January 2022
# OCM Agenda with Attach", each that meeting's only agenda.
_PACKET = re.compile(
    r"(?:\b(?:with(?:out)?|and|incl\w*|excl\w*)|&)[\s(-]+(?:all[\s-]+)?"
    r"attach(?:ments?)?\b",
    re.IGNORECASE,
)

# A revised agenda, which is the one the meeting actually worked from when
# both it and the original are up (Victoria Park, 13 December 2022). Albany
# numbers the revision instead: "ocm_agenda_oct25_v2" beside
# "ocm_agenda_oct25" (28 October 2025), and York calls it "Updated" beside
# "Original" (24 March 2026).
_AMENDED = re.compile(r"amended|revised|updated|(?<![a-z0-9])v[2-9]\b", re.IGNORECASE)

# A full date in a heading or a filename: "21 December 2021", "ocm 21
# december minutes" (year optional in a filename).
_FULL_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\b(?:\s+(\d{{4}}))?",
    re.IGNORECASE,
)

# A label that is a meeting's name and nothing else, once its date is gone.
_ONLY_A_MEETING_NAME = re.compile(r"(?:\w+\s+){0,3}meeting", re.IGNORECASE)

_MONTH_NAME = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
)
_LEADING_MONTH = re.compile(
    rf"^\s*{_MONTH_NAME}(?:\s+\d{{4}})?\s+(?=\w)", re.IGNORECASE
)

# A bare year left at the end ("Annual Electors Meeting, 2025", Leonora) is
# noise too, and so is a month with no day ("Ordinary Council Meeting March
# 2020", Westonia).
_HEADING_NOISE = re.compile(
    r"^\s*(?:final|draft)\b|\b(?:agenda|minutes)\s*$"
    r"|\bat\s+\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\.?"
    rf"|\s+{_MONTH_NAME}(?:\s+\d{{4}})?\s*$"
    r"|,?\s+\d{4}\s*$",
    re.IGNORECASE,
)

# Bodies a council files under its Council meeting types now and then:
# Peppermint Grove an Agenda Briefing Forum under "Ordinary Council Meeting",
# Nedlands its Agenda Forums and Audit Committee there too. Where a scraper
# reads only Council meetings (`meeting_types`), a listing entry whose
# heading names one of these is skipped before its page is fetched.
_NOT_A_COUNCIL_MEETING = re.compile(
    r"forum|briefing|committee|working\s+group|advisory\s+group", re.IGNORECASE
)

# How far ahead an upcoming meeting is worth a request. Agendas go up about a
# week before the meeting; a meeting further out than this has never had
# papers, and it will be fetched on a later night once it is close.
UPCOMING_WINDOW_DAYS = 28

# One name for each kind of electors' meeting, for `canonical_names`. The
# Local Government Act 1995 holds an annual general meeting of electors
# (s 5.27) and, on request, a special meeting of electors (s 5.28). Every
# electors' meeting the councils using this list file is one or the other;
# Cottesloe's "General Meeting of Electors" would need a look before it did.
ELECTORS_NAMES = (
    (
        re.compile(r"special.*elector|elector.*special", re.IGNORECASE),
        "Special Meeting of Electors",
    ),
    (re.compile(r"elector", re.IGNORECASE), "Annual Meeting of Electors"),
)


def _singular(name: str) -> str:
    """One meeting's name, where a type or heading names the series: Leonora's
    types are "Ordinary Council Meetings" and "Special Council Meetings", and
    Moora heads one meeting "Annual Electors Meetings"."""
    return re.sub(r"\b(meeting)s$", r"\1", name, flags=re.IGNORECASE)


def _is_not_found(error: requests.HTTPError) -> bool:
    # A replayed failure is rebuilt from its message alone, with no response
    # attached, so the status is read from the message as well.
    response = getattr(error, "response", None)
    if response is not None:
        return response.status_code == 404
    return str(error).startswith("404")


class CouncilConnectScraper(BaseScraper):
    """Base class for CouncilConnect meeting modules.

    A subclass supplies the site origin and, optionally:

    `inline_documents`
        True where the year listing itself links the PDFs.
    `meeting_types`
        `{type-slug: "Display Name"}` to read only those types, through the
        per-type year pages. None reads every type through one listing.
        A per-type page for a year with no meetings of that type is an empty
        200, not a 404, so a type that skipped a year costs one request.
    `upcoming_path`
        Where upcoming meetings are listed—a path, or a tuple of paths for a
        site whose `/council-meetings/` is a landing page and lists upcoming
        meetings only per type (`/council-meetings/<type>`). None if the site
        has no such page.
    `first_year`
        The first year the site's /past index lists. A year before it 404s,
        which would otherwise fail the whole scrape.
    `type_listings`
        False where the per-type year pages do not answer (Albany's 404 for
        every type), so `meeting_types` is applied to the all-types listing
        instead: a meeting of another type is skipped before its page is
        fetched, and the year costs the all-types listing's pages.
    `body_documents`
        True where a meeting page links its papers in the page's own text
        rather than the documents block: Koorda writes "Agenda", "Minutes"
        and "Attachments" headings in the meeting description, each over a
        link to the site's general file store
        (/Profiles/<site>/Assets/ClientData/...). Same-site PDFs in the
        meeting's details are then read as well.
    `not_a_council_meeting`
        Headings skipped, where `meeting_types` is set, before the meeting's
        page is fetched (see _NOT_A_COUNCIL_MEETING). Leonora heads half its
        Ordinary meetings "Ordinary Council Committee Meeting", so it leaves
        "committee" out.
    `wrong_documents`
        `{url: why}` for documents a council has posted against the wrong
        meeting, checked by reading them. They are never emitted. A filename
        date alone is not enough to judge this—Murray and Nedlands both have
        correct minutes under filenames dated a month off—so each entry is a
        document whose contents were read.
    `accepted_documents`
        `{url: "agenda" | "minutes"}`, the other way round: documents the
        rules would throw away that are, by their contents, this meeting's
        agenda or minutes. Northam labelled two Ordinary meetings' agendas
        "AGENDA - Council Forum Meeting".
    `corrections`
        `{meeting page url: {"date": ..., "time": ..., "name": ...}}` for a
        meeting whose page gives the wrong date, time or name, checked by
        reading its agenda or minutes. Applied last.
    `plausible_times_only`
        True where the date field's time is often the moment the entry was
        made rather than the start time ("1:59 PM", "5:24 PM", "12:00 AM").
        A time off the quarter-hour, or before 7 am or after 8 pm, is then
        left blank rather than emitted as fact (see _plausible_time).
    `canonical_names`
        `((pattern, name), ...)`: the first pattern found in a meeting's
        name replaces it. Headings are hand-typed, so one council's
        electors' meeting can come out as "Annual Electors' Meeting",
        "Annual Meeting of Electors" and "Annual Electors Meeting" in three
        years; see ELECTORS_NAMES.
    """

    inline_documents: bool = False
    meeting_types: Optional[dict[str, str]] = None
    upcoming_path: Optional[str | tuple[str, ...]] = "/council-meetings/"
    first_year: int = EARLIEST_YEAR
    type_listings: bool = True
    body_documents: bool = False
    not_a_council_meeting: re.Pattern = _NOT_A_COUNCIL_MEETING
    wrong_documents: dict[str, str] = {}
    accepted_documents: dict[str, str] = {}
    corrections: dict[str, dict[str, Optional[str]]] = {}
    plausible_times_only: bool = False
    canonical_names: tuple[tuple[re.Pattern, str], ...] = ()

    @staticmethod
    def meeting_type_of(url: str) -> Optional[str]:
        """The type slug in a meeting page's URL ("ordinary-council-meeting"),
        or None if the URL is not a meeting's own page."""
        match = _MEETING_PATH.match(urlparse(url).path)
        return match.group("type") if match else None

    # --- years -------------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    # --- fetching ----------------------------------------------------------

    def _listing_urls(self, year: int) -> list[str]:
        if self.meeting_types is None or not self.type_listings:
            return [f"{self.base_url}/council-meetings/past/{year}"]
        return [
            f"{self.base_url}/council-meetings/{type_slug}/past/{year}"
            for type_slug in self.meeting_types
        ]

    def _listing_pages(self, url: str):
        """Yield each page of a year listing as parsed HTML.

        Page one is a GET; every later page is the form posted back with the
        pager's control as the event target, carrying the view state the
        previous page handed out.
        """
        html = self.fetcher.fetch_with_requests(url)
        page = 1
        while True:
            soup = BeautifulSoup(html, "html.parser")
            yield soup

            target = self._next_page_target(soup, page)
            if not target:
                return
            form = soup.find("form")
            if form is None:
                self.logger.warning(f"No form to post back on {url} page {page}")
                return
            data = self._form_fields(form)
            data["__EVENTTARGET"] = target
            data["__EVENTARGUMENT"] = ""
            html = self.fetcher.fetch_with_requests(
                urljoin(url, form.get("action") or url), method="POST", data=data
            )
            page += 1

    @staticmethod
    def _next_page_target(soup: BeautifulSoup, page: int) -> Optional[str]:
        """The postback target for the page after `page`, or None if last.

        The pager shows at most five numbers, in blocks: "1 2 3 4 5 ...",
        then "... 6 7". The "..." after the numbers posts back to the first
        page of the next block. Victoria Park listed 62 meetings in 2025, and
        following only numbered links stopped every year at 50. The current
        page is a plain span, so a "..." before it—back to the previous
        block—is never followed.
        """
        pager = soup.find(id=re.compile(r"dpMeetings$"))
        if pager is None:
            return None
        forward = None
        past_current = False
        for element in pager.find_all(["a", "span"]):
            text = element.get_text(strip=True)
            if element.name == "span":
                past_current = past_current or text == str(page)
                continue
            if text == str(page + 1) or (
                past_current and text in ("...", "…") and forward is None
            ):
                forward = element
                if text == str(page + 1):
                    break
        if forward is None:
            return None
        match = re.search(r"__doPostBack\('([^']+)'", forward.get("href", ""))
        return match.group(1) if match else None

    @staticmethod
    def _form_fields(form) -> dict[str, str]:
        """The values a browser would post: every named input except buttons.

        Checkboxes are left out because the meeting-type filter's are all
        unticked, and an unticked box is not posted.
        """
        return {
            field["name"]: field.get("value", "")
            for field in form.find_all("input")
            if field.get("name")
            and field.get("type")
            not in ("submit", "button", "image", "checkbox", "radio")
        }

    # --- parsing -----------------------------------------------------------

    def _type_labels(self, soup: BeautifulSoup) -> dict[str, str]:
        """Map type slugs to the names the site gives them.

        The all-types listing has a checkbox per meeting type, labelled with
        its proper name. The slug in a meeting's URL is that name slugified.
        """
        labels = dict(self.meeting_types or {})
        for box in soup.select("input[name*=chkTypes]"):
            label = soup.find("label", attrs={"for": box.get("id")})
            if label:
                name = label.get_text(" ", strip=True)
                labels.setdefault(
                    re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), name
                )
        return labels

    @staticmethod
    def _link_date(link) -> Optional[datetime.date]:
        short = _SHORT_DATE.search(link.get_text(" ", strip=True))
        if short:
            return parse_date(short.group()).date()
        numeric = _TITLE_DATE.search(link.get("title") or "")
        if numeric:
            return parse_date(numeric.group(), dayfirst=True).date()
        return None

    @staticmethod
    def _parse_when(text: str) -> tuple[Optional[datetime.date], Optional[str]]:
        match = _LONG_DATE.search(text or "")
        if not match:
            return None, None
        date = parse_date(match.group("date")).date()
        time = match.group("time")
        if time:
            time = parse_date(time).strftime("%I:%M %p").lstrip("0")
        return date, time

    def _name(self, heading: str, type_slug: Optional[str], labels: dict) -> str:
        """The meeting type, from the heading or the type it is filed under.

        Headings are hand-typed: "Special Council Meetiing", "Council Meeting"
        for an Ordinary one at East Fremantle, a date on one side or the
        other. The type name is the clean version when the heading is a
        misspelling or a vaguer form of it. But a heading that names some
        other meeting wins—East Fremantle files its electors' meeting under
        "Special Council Meeting", and its committees under a type called just
        "Meeting".
        """
        # "(rescheduled from 1 May 2020)" is about the date, not the meeting.
        cleaned = re.sub(r"\([^)]*\d{4}[^)]*\)", "", heading or "")
        cleaned = _HEADING_DATE.sub("", cleaned)
        # "Final Ordinary Council Meeting Agenda", "Special Council Meeting -
        # at 5.30pm": the document's status, its kind and the hour are not
        # part of the meeting's name.
        cleaned = _HEADING_NOISE.sub("", cleaned)
        # "February Ordinary Council Meeting" (Westonia): the month alone,
        # with no day for _HEADING_DATE to anchor on, is still the date.
        cleaned = _LEADING_MONTH.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—,:")
        label = labels.get(type_slug) if type_slug else None
        if label and label.lower() not in _GENERIC_HEADINGS:
            # "Special Meeting of Council" is the same meeting as "Special
            # Council Meeting", worded the other way round, and too far from
            # it letter by letter for the similarity test.
            def comparable(name: str) -> str:
                return re.sub(
                    r"^(\w+)\s+meeting\s+of\s+(?:the\s+)?council\b",
                    r"\1 council meeting",
                    name.lower(),
                )

            similar = (
                difflib.SequenceMatcher(
                    None, comparable(cleaned), comparable(label)
                ).ratio()
                >= 0.85
            )
            # "Ordinary Council Meeting - April 2025 - Reconvened": the type
            # with words after it is still that type.
            extends = comparable(cleaned).startswith(comparable(label))
            if (
                not cleaned
                or cleaned.lower() in _GENERIC_HEADINGS
                or similar
                or extends
            ):
                return _singular(label)
        return _singular(cleaned or label or "Council Meeting")

    def _pick_documents(
        self,
        links: list[tuple[Optional[str], str, str]],
        meeting_name: Optional[str] = None,
        date: Optional[datetime.date] = None,
    ):
        """Choose the agenda and minutes from (group, label, url) triples.

        `group` is the heading the link sits under on a meeting page, or None
        on an inline listing, where nothing groups them and the label decides.
        Only PDFs count: the inline listings put MP3 recordings labelled "OCM
        Minutes ... Audio Recording" next to the minutes.

        `meeting_name` is the meeting's heading and type name. A document that
        names a briefing, an audit committee, a committee or an electors'
        meeting the meeting's name does not is another body's paper (see
        _OTHER_BODY) and is not read.

        `date` is the meeting's. A label that names some other full date is
        tried last: Albany's 3 February 2021 electors' meeting page carries
        "Special Electors Meeting - Minutes - 8 December 2020" and "Annual
        Electors Meeting - Minutes - 16 December 2019" ahead of its own.
        """
        own_bodies = {body.lower() for body in _OTHER_BODY.findall(meeting_name or "")}
        agendas, minutes, unnamed = [], [], []
        for group, label, url in links:
            if url in self.wrong_documents:
                continue
            # Ahead of every rule below, and of the documents they pass:
            # each entry was read and is this meeting's.
            kind = self.accepted_documents.get(url)
            if kind:
                (agendas if kind == "agenda" else minutes).insert(
                    0, (f"{label} {kind}", url)
                )
                continue
            path = urlparse(url).path
            if not path.lower().endswith(".pdf"):
                continue
            filename = path.rsplit("/", 1)[-1]
            text = f"{label} {filename}"
            if meeting_name is not None and any(
                body.lower() not in own_bodies
                for body in _OTHER_BODY.findall(f"{label} {unquote(filename)}")
            ):
                continue
            # "Agenda - 23 July 2024 with attachments" is the agenda packet,
            # not an attachment—and at Nedlands, whose bare agendas are Word
            # files, often the only PDF agenda there is.
            if _NOT_THE_MEETINGS.search(_PACKET.sub("", label)):
                continue
            # Filenames such as "with-all-attachments" describe a packet, not
            # an attachment, when the label names the agenda or minutes; see
            # _NOT_THE_MEETINGS_FILE. Hyphens and underscores stand in for
            # spaces in filenames, so \b-anchored terms still match.
            label_names_it = _AGENDA.search(label) or _MINUTES.search(label)
            file_test = _NOT_THE_MEETINGS_FILE if label_names_it else _NOT_THE_MEETINGS
            if file_test.search(_PACKET.sub("", filename.replace("_", " "))):
                continue
            if group and _ATTACHMENT_GROUP.search(group):
                continue
            # The group is trusted, except where the label plainly names the
            # other document: Bassendean has filed a meeting's agenda
            # ("Special-Council-Agenda-31-January-2023") under "Minutes".
            names_agenda = _AGENDA.search(label) and not _MINUTES.search(label)
            names_minutes = _MINUTES.search(label) and not _AGENDA.search(label)
            if group and _MINUTES_GROUP.search(group) and not names_agenda:
                minutes.append((text, url))
            elif group and _AGENDA_GROUP.search(group) and not names_minutes:
                agendas.append((text, url))
            elif _MINUTES.search(text):
                minutes.append((text, url))
            elif _AGENDA.search(text):
                agendas.append((text, url))
            elif group and _ONLY_A_MEETING_NAME.fullmatch(
                _HEADING_DATE.sub("", re.sub(r"[_-]+", " ", label)).strip(" ,-–—")
            ):
                unnamed.append(url)

        if date is not None:
            agendas.sort(key=lambda t_u: self._names_another_date(t_u[0], date))
            minutes.sort(key=lambda t_u: self._names_another_date(t_u[0], date))

        # Within a group, the document actually called the agenda wins over a
        # stray report filed beside it, and the bare agenda over a packet
        # bundled with its attachments when the council posts both. An
        # amended agenda beats the original it replaced.
        agenda_url = (
            next(
                (
                    u
                    for t, u in agendas
                    if _AGENDA.search(t)
                    and _AMENDED.search(t)
                    and not _ATTACHMENT_GROUP.search(t)
                ),
                None,
            )
            or next(
                (
                    u
                    for t, u in agendas
                    if _AGENDA.search(t) and not _ATTACHMENT_GROUP.search(t)
                ),
                None,
            )
            or next((u for t, u in agendas if _AGENDA.search(t)), None)
            or (agendas[0][1] if agendas else None)
        )
        # A vague group ("Downloads") holding the minutes, an attachments
        # bundle and one PDF labelled with nothing but the meeting and its
        # date ("Ordinary Council Meeting Tuesday 25 July 2023"): that one is
        # the agenda. A label with anything more ("Special Council Meeting 21
        # Feb_Adverse Possession Claim") could be a report, and with two such
        # PDFs nothing says which, so neither case is read this way.
        if agenda_url is None and len(unnamed) == 1:
            agenda_url = unnamed[0]
        # Confirmed minutes supersede unconfirmed ones when both are up—also
        # where only the "Minutes" group says what they are: Northam's 26
        # November 2025 pair is "Ordinary Council Meeting - PART 1 PUBLIC
        # (UNCONFIRMED)" and "... (CONFIRMED)", with "minutes" in neither.
        # Minutes that say they are confirmed beat ones that say neither:
        # Northam's 28 January 2026 pair is "... Part 1 PUBLIC" (posted
        # first) and "... Part 1 PUBLIC (CONFIRMED)".
        minutes_url = (
            next(
                (
                    u
                    for t, u in minutes
                    if _MINUTES.search(t)
                    and _CONFIRMED.search(t)
                    and not _UNCONFIRMED.search(t)
                ),
                None,
            )
            or next(
                (
                    u
                    for t, u in minutes
                    if _MINUTES.search(t) and not _UNCONFIRMED.search(t)
                ),
                None,
            )
            or next((u for t, u in minutes if _MINUTES.search(t)), None)
            or next((u for t, u in minutes if not _UNCONFIRMED.search(t)), None)
            or (minutes[0][1] if minutes else None)
        )
        return agenda_url, minutes_url

    def _detail_links(self, soup: BeautifulSoup, page_url: str):
        """(group, label, url) for each document on a meeting page."""
        own_path = urlparse(page_url).path.rstrip("/") + "/documents/"
        links = []
        # Most sites wrap the groups in a "...documents" block. Victoria Park's
        # template has none: its groups ("Documents", "Attachments") are h3s
        # straight inside div.cm-plugin-content, which is read only when the
        # usual block is missing so no other site's links are read twice.
        containers = soup.find_all(class_=re.compile(r"documents$", re.I)) or (
            soup.find_all(class_="cm-plugin-content")
        )
        for container in containers:
            group = ""
            for element in container.find_all(["h3", "a"]):
                if element.name == "h3":
                    group = element.get_text(" ", strip=True)
                    continue
                href = element.get("href")
                if not href:
                    continue
                # Victoria Park's filenames can carry raw spaces ("ordinary
                # council meeting - 20 august 2024.pdf"); a URL must not.
                url = requote_uri(urljoin(page_url, href))
                if not unquote(urlparse(url).path).startswith(unquote(own_path)):
                    continue
                links.append(
                    (
                        group,
                        element.get("title") or element.get_text(" ", strip=True),
                        url,
                    )
                )
        if self.body_documents:
            links.extend(self._body_links(soup, page_url, {u for _, _, u in links}))
        return links

    def _body_links(self, soup: BeautifulSoup, page_url: str, known: set[str]):
        """(group, label, url) for PDFs linked in the meeting's own details.

        Only `div.meeting-info` is read—the heading, date and description—so
        the strategic plan and budget PDFs the site links from its menus and
        footer never count. A link must stay on the council's own site; the
        audio recordings beside the papers are on Google Drive.
        """
        info = soup.find(class_="meeting-info")
        if info is None:
            return []
        host = urlparse(self.base_url).netloc
        links, group = [], ""
        for element in info.find_all(["h3", "a"]):
            if element.name == "h3":
                group = element.get_text(" ", strip=True)
                continue
            href = element.get("href")
            if not href:
                continue
            url = requote_uri(urljoin(page_url, href))
            parsed = urlparse(url)
            if (
                parsed.netloc != host
                or not parsed.path.lower().endswith(".pdf")
                or url in known
            ):
                continue
            known.add(url)
            # The text ("October 2025 Agenda") is the label here; the title
            # ("Click here to download the October Minutes") is the prompt.
            label = element.get_text(" ", strip=True) or element.get("title") or ""
            links.append((group, label, url))
        return links

    def _meeting_from_detail(
        self, url: str, labels: dict, fallback_when=None
    ) -> Optional[ScraperReturn]:
        html = self.fetcher.fetch_with_requests(url)
        soup = BeautifulSoup(html, "html.parser")
        info = soup.find(class_="meeting-info")
        if info is None:
            self.logger.warning(f"No meeting details on {url}")
            return None

        heading = info.find("h1")
        when = info.find(["h2", "h4"])
        date, time = self._parse_when(when.get_text(" ", strip=True) if when else "")
        if date is None and fallback_when:
            date, time = fallback_when
        # Bassendean's meeting pages give the date alone; its listing gives
        # the time as well.
        elif time is None and fallback_when and fallback_when[0] == date:
            time = fallback_when[1]
        if date is None:
            self.logger.warning(f"No date on {url}")
            return None

        match = _MEETING_PATH.match(urlparse(url).path)
        type_slug = match.group("type") if match else None
        heading_text = heading.get_text(" ", strip=True) if heading else ""

        # "View Agenda - ..." is the link's title attribute; the text adds the
        # file size, which is noise.
        agenda_url, minutes_url = self._pick_documents(
            [
                (group, re.sub(r"^View\s+", "", label), href)
                for group, label, href in self._detail_links(soup, url)
            ],
            meeting_name=f"{heading_text} {labels.get(type_slug) or type_slug or ''}",
            date=date,
        )
        if not agenda_url and not minutes_url:
            return None

        date = self._heading_date_if_documents_agree(
            heading.get_text(" ", strip=True) if heading else "",
            date,
            [u for u in (agenda_url, minutes_url) if u],
        )

        location = soup.select_one(".meeting-location")
        location_text = None
        if location:
            location_text = (
                re.sub(r"^\s*Location:\s*", "", location.get_text(" ", strip=True))
                or None
            )

        meeting = ScraperReturn(
            name=self._canonical_name(self._name(heading_text, type_slug, labels)),
            date=date.isoformat(),
            time=self._plausible_time(time),
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location_text,
        )
        for field, value in self.corrections.get(url, {}).items():
            setattr(meeting, field, value)
        return meeting

    def _canonical_name(self, name: str) -> str:
        for pattern, canonical in self.canonical_names:
            if pattern.search(name):
                return canonical
        return name

    def _plausible_time(self, time: Optional[str]) -> Optional[str]:
        """`time`, or None where `plausible_times_only` says it is an entry
        stamp. Councils start on a quarter-hour; a field reading
        "5:24 PM" when the agenda says 5.30 pm is when someone saved it."""
        if not time or not self.plausible_times_only:
            return time
        start = datetime.datetime.strptime(time, "%I:%M %p").time()
        if (
            start.minute % 15
            or start < datetime.time(7, 0)
            or start > datetime.time(20, 0)
        ):
            return None
        return time

    @staticmethod
    def _names_another_date(text: str, date: datetime.date) -> bool:
        """Whether `text` names a full date, year and all, and not `date`."""
        named = []
        for day, month, year in _FULL_DATE.findall(text):
            if not year:
                continue
            try:
                named.append(parse_date(f"{day} {month} {year}").date())
            except (ValueError, OverflowError):
                continue
        return bool(named) and date not in named

    @staticmethod
    def _names_date(text: str, date: datetime.date) -> bool:
        """Whether `text` names `date`'s day and month (and year, if any).

        Northam's filenames start with the date as digits instead
        ("20230712-agenda-special-council-meeting.pdf").
        """
        if re.search(rf"(?<!\d){date:%Y%m%d}(?!\d)", text):
            return True
        for day, month, year in _FULL_DATE.findall(text):
            try:
                named = parse_date(f"{day} {month} {year or date.year}").date()
            except (ValueError, OverflowError):
                continue
            if named == date:
                return True
        return False

    def _heading_date_if_documents_agree(
        self, heading: str, date: datetime.date, document_urls: list[str]
    ) -> datetime.date:
        """The heading's date where the documents back it over the date field.

        The structured date field is right almost everywhere, and the heading
        is hand-typed: Nedlands' 28 January 2026 meeting is headed "28
        January 2025". But Peppermint Grove's 21 December 2021 meeting has
        14 December in the date field, while its heading, agenda and minutes
        all say the 21st. The URL slug is made from the heading, so it is no
        second witness; the document filenames are. The heading wins only
        when a filename names its date and none names the field's.
        """
        match = re.search(
            rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}", heading, re.I
        )
        if not match:
            return date
        try:
            headed = parse_date(match.group()).date()
        except (ValueError, OverflowError):
            return date
        if headed == date:
            return date
        filenames = [
            re.sub(r"[-_.]+", " ", unquote(urlparse(u).path.rsplit("/", 1)[-1]))
            for u in document_urls
        ]
        if any(self._names_date(f, headed) for f in filenames) and not any(
            self._names_date(f, date) for f in filenames
        ):
            self.logger.info(
                f"Date field says {date}, heading and documents say {headed}: "
                f"using {headed}"
            )
            return headed
        return date

    @staticmethod
    def _stable_document_url(detail_url: str, href: str) -> str:
        """The meeting page's address for a document the listing links.

        The listing links the file store directly:
        /Profiles/<site>/assets/moduledata/councilmeetings/<guid>/<ver>/<File>.pdf.
        `<ver>` goes up every time the council edits the meeting—posting the
        minutes, adding a recording—so the same agenda moves from 1.1 to 1.4
        to 1.5 over a month (the older paths keep answering, the newer the
        listing links). council-alerts keys a meeting on its agenda_url, so a
        moving URL would make a new meeting each time.

        The meeting page links the same file as
        <meeting page>/documents/<file lowercased>, with no version, and an
        upcoming meeting—read from that page—already has that form, so it
        keeps its URL when it moves to the year listing. Every filename on
        East Fremantle's listings is hyphenated ASCII, which the meeting page
        changes only by lowercasing; 50 of 50 constructed URLs sampled across
        2020–2026 answered with a PDF (19 Oct 2026).
        """
        filename = urlparse(href).path.rsplit("/", 1)[-1]
        return f"{detail_url}/documents/{filename.lower()}"

    def _meeting_from_summary(
        self, summary, page_url: str, labels: dict
    ) -> Optional[ScraperReturn]:
        """A meeting read straight off an inline-documents listing."""
        heading = summary.find(["h2", "h3"])
        when = summary.find(class_="meeting-date")
        date, time = self._parse_when(when.get_text(" ", strip=True) if when else "")
        if date is None:
            self.logger.warning(f"Undated meeting on {page_url}: {heading}")
            return None

        detail_url, type_slug = None, None
        for link in summary.find_all("a", href=True):
            match = _MEETING_PATH.match(urlparse(urljoin(page_url, link["href"])).path)
            if match:
                detail_url = urljoin(page_url, link["href"]).rstrip("/")
                type_slug = match.group("type")
        if detail_url is None:
            # Without the meeting's own page there is no stable address for
            # its documents (see below), and a versioned one would duplicate
            # the meeting downstream every time the council edits it.
            self.logger.warning(f"No meeting page for {heading} on {page_url}")
            return None

        # The summary lists "Agenda and Minutes" first and sometimes a second
        # "Additional Meeting Documents" list, where East Fremantle has put a
        # meeting's only agenda or minutes. Every list is read, first list
        # first, so the main agenda still wins when both have one.
        links = []
        for documents in summary.find_all("ul", class_="meeting-documents"):
            for link in documents.find_all("a", href=True):
                label = link.get("title") or link.get_text(" ", strip=True)
                label = re.sub(r"^Click to download\s+", "", label)
                links.append(
                    (None, label, self._stable_document_url(detail_url, link["href"]))
                )
        heading_text = heading.get_text(" ", strip=True) if heading else ""
        agenda_url, minutes_url = self._pick_documents(
            links,
            meeting_name=f"{heading_text} {labels.get(type_slug) or type_slug or ''}",
            date=date,
        )
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=self._canonical_name(self._name(heading_text, type_slug, labels)),
            date=date.isoformat(),
            time=self._plausible_time(time),
            webpage_url=detail_url or page_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    # --- the scrape ----------------------------------------------------------

    def _past_meetings(self, years: list[int], seen: set[str]) -> list[ScraperReturn]:
        results = []
        for year in years:
            for listing_url in self._listing_urls(year):
                # A failed listing page is not caught: it would drop the whole
                # year (production asks for one) and still report success.
                # The one exception is a 404 for this year. A year with no
                # meetings in the module has no listing at all (Nedlands'
                # /past/2027 404s in October 2026), and that is what the new
                # year looks like every January until its first meeting is
                # entered; the upcoming page is then all there is.
                try:
                    pages = list(self._listing_pages(listing_url))
                except requests.HTTPError as e:
                    if year == clock.current_year() and _is_not_found(e):
                        self.logger.info(f"No listing yet for {year}: {listing_url}")
                        continue
                    raise

                labels = {}
                for soup in pages:
                    labels.update(self._type_labels(soup))
                self._labels.update(labels)

                for soup in pages:
                    for summary in soup.select(".council-meeting-summary"):
                        results.extend(
                            self._summary_meeting(
                                summary, listing_url, labels, year, seen
                            )
                        )
        return results

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        if self.meeting_types is not None and not self.type_listings:
            # The all-types listing, read for some types only: the type is
            # in each meeting link's path.
            types = {
                self.meeting_type_of(urljoin(listing_url, link["href"]))
                for link in summary.find_all("a", href=True)
            }
            if not types & set(self.meeting_types):
                return []
        if self.inline_documents:
            meeting = self._meeting_from_summary(summary, listing_url, labels)
            if meeting is None or meeting.webpage_url in seen:
                return []
            if meeting.webpage_url != listing_url:
                seen.add(meeting.webpage_url)
            return [meeting] if parse_date(meeting.date).year == year else []

        heading = summary.find(["h2", "h3"])
        if (
            self.meeting_types is not None
            and heading
            and self._screens_committees(listing_url)
        ):
            if self.not_a_council_meeting.search(heading.get_text(" ", strip=True)):
                return []
        for link in summary.find_all("a", href=True):
            url = urljoin(listing_url, link["href"])
            if not _MEETING_PATH.match(urlparse(url).path) or url in seen:
                continue
            seen.add(url)
            when = summary.find(class_="meeting-date")
            fallback = self._parse_when(when.get_text(" ", strip=True) if when else "")
            if fallback[0] and fallback[0].year != year:
                return []
            meeting = self._read_meeting(url, labels, fallback)
            return [meeting] if meeting else []
        return []

    def _screens_committees(self, listing_url: str) -> bool:
        """Whether entries on this listing whose heading names a committee or
        forum are skipped (see `_NOT_A_COUNCIL_MEETING`). Always, here: with
        `meeting_types` set, the types read are Council meetings."""
        return True

    def _read_meeting(self, url, labels, fallback) -> Optional[ScraperReturn]:
        """One meeting page, or None where the page is gone or unreadable.

        A failed fetch is not caught, like a failed listing: after the
        fetcher's retries, a 5xx or a timeout means the site is in trouble,
        and carrying on would report success with meetings missing. Two
        failures are one meeting's alone and are skipped with a warning: a
        404 (the listing links a meeting page that has since been deleted)
        and a page this code cannot parse.
        """
        try:
            return self._meeting_from_detail(url, labels, fallback)
        except requests.HTTPError as e:
            if not _is_not_found(e):
                raise
            self.logger.warning(f"Meeting page gone (404): {url}")
        except requests.RequestException:
            raise
        except Exception as e:
            self.logger.warning(f"Could not parse {url}: {e!r}")
        return None

    def _upcoming_meetings(
        self, wanted: set[int], seen: set[str]
    ) -> list[ScraperReturn]:
        paths = (
            (self.upcoming_path,)
            if isinstance(self.upcoming_path, str)
            else self.upcoming_path
        )
        results = []
        for path in paths:
            results.extend(
                self._upcoming_from(urljoin(self.base_url, path), wanted, seen)
            )
        return results

    def _upcoming_from(
        self, url: str, wanted: set[int], seen: set[str]
    ) -> list[ScraperReturn]:
        # Not caught, like the year listings: losing this page loses every
        # meeting whose agenda is out but whose date has not yet passed.
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

        labels = {**self._labels, **self._type_labels(soup)}
        horizon = clock.today() + datetime.timedelta(days=UPCOMING_WINDOW_DAYS)
        results = []
        for link in soup.find_all("a", href=True):
            meeting_url = urljoin(url, link["href"])
            match = _MEETING_PATH.match(urlparse(meeting_url).path)
            if not match or meeting_url in seen:
                continue
            # Each upcoming meeting is linked twice on some sites—a dated
            # button, then an undated "View Meeting Details"—so a meeting
            # judged by its first link is settled for both.
            seen.add(meeting_url)
            if (
                self.meeting_types is not None
                and match.group("type") not in self.meeting_types
            ):
                continue

            # The button text carries the date ("Tue 27 Oct 2026"), which is
            # enough to skip meetings outside the wanted years or too far off
            # to have papers, without spending a request on them. Murray's
            # all-types upcoming page has no dated button; its link title ends
            # with the date instead ("View details for ... - 22/10/2026").
            date = self._link_date(link)
            if date and (date.year not in wanted or date > horizon):
                continue
            # The button's time, for a meeting page that gives only the date.
            time = _BUTTON_TIME.search(link.get_text(" ", strip=True))
            fallback = (
                date,
                time and parse_date(time.group()).strftime("%I:%M %p").lstrip("0"),
            )
            meeting = self._read_meeting(meeting_url, labels, fallback)
            if meeting and parse_date(meeting.date).year in wanted:
                results.append(meeting)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        # Year listings only ever hold meetings that have happened, so a year
        # past this one has nothing to list; its meetings are on the upcoming
        # page until their dates pass.
        past_years = sorted(
            (y for y in wanted if self.first_year <= y <= this_year), reverse=True
        )

        # Past first: the year listings name the meeting types, which the
        # upcoming page does not, and a meeting that has just happened can
        # sit on both—the listing's copy is the one kept.
        seen: set[str] = set()
        self._labels: dict[str, str] = dict(self.meeting_types or {})
        past = self._past_meetings(past_years, seen)
        upcoming = []
        if self.upcoming_path and max(wanted) >= this_year:
            upcoming = self._upcoming_meetings(wanted, seen)
        results = upcoming + past

        if not results:
            raise RuntimeError(
                f"{self.council_name}: no meetings with documents for "
                f"{sorted(wanted)}; the meetings module may have changed"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results


class CouncilConnectArchive(CouncilConnectScraper):
    """A CouncilConnect meetings module read on behalf of another scraper.

    For a council that moved its meetings to another platform (Resolve at
    East Pilbara and Alice Springs, DocsPublished at Nannup) and left its
    older papers in the module, which the site still serves. It borrows the
    owner's fetcher, so its requests are made, recorded and replayed as the
    owner's, like `OpenCitiesArchive` and Mundaring's library.

    `meeting_types` is as on the base class: per-type year listings, or None
    for the all-types one. `before` in `read` is the day the council moved:
    a meeting the listing dates on or after it is skipped before its page is
    fetched, because the other platform has it, and the archive's copy is
    often the half-finished one (East Pilbara's late-2024 pages have the
    minutes and not the agenda). Upcoming meetings are on the other platform,
    so the upcoming page is never read.
    """

    upcoming_path = None

    def __init__(
        self,
        owner: BaseScraper,
        origin: str,
        meeting_types: Optional[dict[str, str]] = None,
        wrong_documents: Optional[dict[str, str]] = None,
        untimed_before: Optional[datetime.date] = None,
    ):
        super().__init__(owner.council_name, owner.state, origin)
        self.fetcher = owner.fetcher
        self.logger = owner.logger
        self.meeting_types = meeting_types
        self.wrong_documents = wrong_documents or {}
        # Meetings before this day are emitted without a time. The module's
        # time field is free-typed by whoever uploads the papers, and some
        # councils left it at a default (6:00 PM on every Alice Springs
        # entry) or stamped the upload time in it (Nannup's 2020 entries say
        # 8:35 or 9:15 AM for 5.30pm meetings). A missing time is honest; a
        # wrong one sends people to the chamber at the wrong hour. Set from
        # checking the field against the agendas.
        self.untimed_before = untimed_before
        self.before: Optional[datetime.date] = None

    def _screens_committees(self, listing_url: str) -> bool:
        # A committee's own per-type listing names every entry after the
        # committee ("Development Committee Meeting - 07 December 2020", Alice
        # Springs), and the owner asked for it by type, so its entries are
        # not screened out as committees filed under a Council type.
        match = _TYPE_LISTING_PATH.match(urlparse(listing_url).path)
        if match and self.meeting_types:
            label = self.meeting_types.get(match.group("type"), "")
            if _NOT_A_COUNCIL_MEETING.search(label):
                return False
        return True

    def read(
        self,
        years: set[int],
        before: Optional[datetime.date] = None,
        allow_empty: bool = False,
    ) -> list[ScraperReturn]:
        """The wanted years' meetings, less any on or after `before`.

        A failed listing or meeting page raises, as in the base class, and so
        does a read that finds nothing, unless `allow_empty`: for a body that
        may simply not have met in the years asked for, where the owner's
        other reads carry the council."""
        self.years_filter = sorted(years)
        self.before = before
        self._labels = dict(self.meeting_types or {})
        this_year = clock.current_year()
        results = self._past_meetings(
            sorted(
                (y for y in years if self.first_year <= y <= this_year), reverse=True
            ),
            set(),
        )
        if not results and not allow_empty:
            raise RuntimeError(
                f"{self.council_name}: no meetings with documents in the "
                f"CouncilConnect archive at {self.base_url} for {sorted(years)}"
            )
        if before:
            # The listing's date decides what is fetched; the meeting page's
            # own date, which can differ, decides what is kept.
            results = [r for r in results if r.date < before.isoformat()]
        for record in results:
            # Older entries carry a date and no time, which the module stores
            # as midnight; "12:00 AM" would claim a time nobody published.
            if record.time == "12:00 AM":
                record.time = None
            if self.untimed_before and record.date < self.untimed_before.isoformat():
                record.time = None
        return results

    def _read_meeting(self, url, labels, fallback) -> Optional[ScraperReturn]:
        if self.before and fallback[0] and fallback[0] >= self.before:
            return None
        return super()._read_meeting(url, labels, fallback)
