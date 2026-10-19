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
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# A meeting's own page: /council-meetings/<type>/<slug>/<id>. Listing and
# per-type paths have "past" or no numeric id, so the trailing id is what
# tells a meeting apart from navigation.
_MEETING_PATH = re.compile(
    r"^/council-meetings/(?P<type>[a-z0-9-]+)/[^/]+/(?P<id>\d+)/?$"
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
_MINUTES = re.compile(r"minut", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfir", re.IGNORECASE)
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
_NOT_THE_MEETINGS = re.compile(
    r"attach|\blate\b|supplement|addend|presentation|notice.of.motion|forum"
    r"|tabled|\breport\s+(?:no\.?\s*)?\d"
    r"|^\s*item\b|^\s*\d+(?:\.\d+)+",
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

# Headings that say nothing a meeting type does not say better.
_GENERIC_HEADINGS = {"council meeting", "meeting", "meeting details"}

_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# Strips "16 December 2025 - ", "7 July - " and "- 12 November 2025" from a
# heading, leaving the meeting's name.
_HEADING_DATE = re.compile(
    rf"(?:{_WEEKDAY}\s*)?\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b(?:\s+\d{{4}})?",
    re.IGNORECASE,
)

# How far ahead an upcoming meeting is worth a request. Agendas go up about a
# week before the meeting; a meeting further out than this has never had
# papers, and it will be fetched on a later night once it is close.
UPCOMING_WINDOW_DAYS = 28


class CouncilConnectScraper(BaseScraper):
    """Base class for CouncilConnect meeting modules.

    A subclass supplies the site origin and, optionally:

    `inline_documents`
        True where the year listing itself links the PDFs.
    `meeting_types`
        `{type-slug: "Display Name"}` to read only those types, through the
        per-type year pages. None reads every type through one listing.
    `upcoming_path`
        Where upcoming meetings are listed; None if the site has no such page.
    """

    inline_documents: bool = False
    meeting_types: Optional[dict[str, str]] = None
    upcoming_path: Optional[str] = "/council-meetings/"

    # --- years -------------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    # --- fetching ----------------------------------------------------------

    def _listing_urls(self, year: int) -> list[str]:
        if self.meeting_types is None:
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
        pager = soup.find(id=re.compile(r"dpMeetings$"))
        if pager is None:
            return None
        for link in pager.find_all("a", href=True):
            if link.get_text(strip=True) != str(page + 1):
                continue
            match = re.search(r"__doPostBack\('([^']+)'", link["href"])
            if match:
                return match.group(1)
        return None

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
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—,:")
        label = labels.get(type_slug) if type_slug else None
        if label and label.lower() not in _GENERIC_HEADINGS:
            similar = (
                difflib.SequenceMatcher(None, cleaned.lower(), label.lower()).ratio()
                >= 0.85
            )
            if not cleaned or cleaned.lower() in _GENERIC_HEADINGS or similar:
                return label
        return cleaned or label or "Council Meeting"

    def _pick_documents(self, links: list[tuple[Optional[str], str, str]]):
        """Choose the agenda and minutes from (group, label, url) triples.

        `group` is the heading the link sits under on a meeting page, or None
        on an inline listing, where nothing groups them and the label decides.
        Only PDFs count: the inline listings put MP3 recordings labelled "OCM
        Minutes ... Audio Recording" next to the minutes.
        """
        agendas, minutes = [], []
        for group, label, url in links:
            path = urlparse(url).path
            if not path.lower().endswith(".pdf"):
                continue
            filename = path.rsplit("/", 1)[-1]
            text = f"{label} {filename}"
            if _NOT_THE_MEETINGS.search(label):
                continue
            # Filenames such as "with-all-attachments" describe a packet, not
            # an attachment, when the label names the agenda or minutes; see
            # _NOT_THE_MEETINGS_FILE. Hyphens and underscores stand in for
            # spaces in filenames, so \b-anchored terms still match.
            label_names_it = _AGENDA.search(label) or _MINUTES.search(label)
            file_test = _NOT_THE_MEETINGS_FILE if label_names_it else _NOT_THE_MEETINGS
            if file_test.search(filename.replace("_", " ")):
                continue
            if group and _ATTACHMENT_GROUP.search(group):
                continue
            if group and _MINUTES_GROUP.search(group):
                minutes.append((text, url))
            elif group and _AGENDA_GROUP.search(group):
                agendas.append((text, url))
            elif _MINUTES.search(text):
                minutes.append((text, url))
            elif _AGENDA.search(text):
                agendas.append((text, url))

        # Within a group, the document actually called the agenda wins over a
        # stray report filed beside it, and the bare agenda over a packet
        # bundled with its attachments when the council posts both.
        agenda_url = (
            next(
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
        # Confirmed minutes supersede unconfirmed ones when both are up.
        minutes_url = (
            next(
                (
                    u
                    for t, u in minutes
                    if _MINUTES.search(t) and not _UNCONFIRMED.search(t)
                ),
                None,
            )
            or next((u for t, u in minutes if _MINUTES.search(t)), None)
            or (minutes[0][1] if minutes else None)
        )
        return agenda_url, minutes_url

    def _detail_links(self, soup: BeautifulSoup, page_url: str):
        """(group, label, url) for each document on a meeting page."""
        own_path = urlparse(page_url).path.rstrip("/") + "/documents/"
        links = []
        for container in soup.find_all(class_=re.compile(r"documents$", re.I)):
            group = ""
            for element in container.find_all(["h3", "a"]):
                if element.name == "h3":
                    group = element.get_text(" ", strip=True)
                    continue
                href = element.get("href")
                if not href:
                    continue
                url = urljoin(page_url, href)
                if not urlparse(url).path.startswith(own_path):
                    continue
                links.append(
                    (
                        group,
                        element.get("title") or element.get_text(" ", strip=True),
                        url,
                    )
                )
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
        if date is None:
            self.logger.warning(f"No date on {url}")
            return None

        # "View Agenda - ..." is the link's title attribute; the text adds the
        # file size, which is noise.
        agenda_url, minutes_url = self._pick_documents(
            [
                (group, re.sub(r"^View\s+", "", label), href)
                for group, label, href in self._detail_links(soup, url)
            ]
        )
        if not agenda_url and not minutes_url:
            return None

        location = soup.select_one(".meeting-location")
        location_text = None
        if location:
            location_text = (
                re.sub(r"^\s*Location:\s*", "", location.get_text(" ", strip=True))
                or None
            )

        match = _MEETING_PATH.match(urlparse(url).path)
        return ScraperReturn(
            name=self._name(
                heading.get_text(" ", strip=True) if heading else "",
                match.group("type") if match else None,
                labels,
            ),
            date=date.isoformat(),
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location_text,
        )

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
        agenda_url, minutes_url = self._pick_documents(links)
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=self._name(
                heading.get_text(" ", strip=True) if heading else "", type_slug, labels
            ),
            date=date.isoformat(),
            time=time,
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
                pages = list(self._listing_pages(listing_url))

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
        if self.inline_documents:
            meeting = self._meeting_from_summary(summary, listing_url, labels)
            if meeting is None or meeting.webpage_url in seen:
                return []
            if meeting.webpage_url != listing_url:
                seen.add(meeting.webpage_url)
            return [meeting] if parse_date(meeting.date).year == year else []

        for link in summary.find_all("a", href=True):
            url = urljoin(listing_url, link["href"])
            if not _MEETING_PATH.match(urlparse(url).path) or url in seen:
                continue
            seen.add(url)
            when = summary.find(class_="meeting-date")
            fallback = self._parse_when(when.get_text(" ", strip=True) if when else "")
            if fallback[0] and fallback[0].year != year:
                return []
            try:
                meeting = self._meeting_from_detail(url, labels, fallback)
            except Exception as e:
                self.logger.warning(f"Could not read {url}: {e}")
                return []
            return [meeting] if meeting else []
        return []

    def _upcoming_meetings(
        self, wanted: set[int], seen: set[str]
    ) -> list[ScraperReturn]:
        url = urljoin(self.base_url, self.upcoming_path)
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
            # to have papers, without spending a request on them.
            short = _SHORT_DATE.search(link.get_text(" ", strip=True))
            if short:
                date = parse_date(short.group()).date()
                if date.year not in wanted or date > horizon:
                    continue
            try:
                meeting = self._meeting_from_detail(meeting_url, labels)
            except Exception as e:
                self.logger.warning(f"Could not read {meeting_url}: {e}")
                continue
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
        past_years = sorted((y for y in wanted if y <= this_year), reverse=True)

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
