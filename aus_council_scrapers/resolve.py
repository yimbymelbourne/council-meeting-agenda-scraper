"""Councils publishing through Resolve (resolve.red).

Resolve is Redman Solutions' meeting system, sold in Australia under the
CivicClerk name and descended from BoardSync. Each council is a tenant on a
shared platform: a React portal at `https://<tenant>.resolve.red/portal/`,
over a JSON API at `https://api.resolve.red` that selects the tenant by a
mandatory `X-RESOLVE-CLIENT` header. Without the header the API answers 400
"Client is not specified", and there is no query-parameter equivalent.

What a scraper needs, and what it costs:

- **Meetings come from one paged list.** `/public/Events?type=past` with a
  date range returns 20 events a page, newest first. Despite the name it is
  bounded only by the range, so future-dated events come back too. The list
  gives the name, `eventDate`, `meetingTypeName`, `agendaId` and
  `isAgendaPublished`, but says nothing about which documents exist: its
  `agendaFile`, `packetFile` and `minutesFile` are null on every event.

- **Which documents exist costs one request per meeting.** The per-event
  detail call, `/public/Events/<id>`, fills those three in. It is 3 to 330 KB
  (the agenda items' HTML comes with it), but it is one request for all three
  answers, and the request count is what a nightly run pays for. Nothing
  cheaper will do: `isAgendaPublished` is not proof of an agenda file—
  Woollahra's 30 March 2026 Council meeting and Mitcham's 6 August 2026
  panel are published with a packet but no agenda, and Mitcham's 10 July 2025
  special panel with minutes alone—and probing each document URL would cost
  two or three requests a meeting instead of one.

- **Documents have one stable URL each.** The API's own document links
  (`/public/AgendaFiles?id=&type=&token=`) hand back an Azure SAS URL that
  expires a minute after it is minted, which is what stalled #145. The older
  DevExpress half of the platform still serves
  `https://<tenant>.resolve.red/web/UserControls/DocPreview.aspx?aoid=<agendaId>`,
  which takes no token and 302s to a freshly signed blob on every request.
  So that URL never expires. The bare URL is the agenda, `&p=1` the packet
  and `&m=1` the minutes; each answers a 1.4 KB "no file" page, not a 404,
  when that document does not exist.

- **The packet is the agenda that has the reports in it.** On every tenant's
  current template the bare agenda is a 2-5 page order of business: item
  titles, no officer reports, no recommendations (Hunters Hill 22 Sep 2026: 2
  pages; its packet is 66 MB). Mitcham's 2020-2023 panel agendas are a
  one-page cover whose content is attached to an item, which only the packet
  includes. So `agenda_url` is the packet where there is one and the bare
  agenda otherwise (`prefer_packet`). Comparing the two documents' sizes at
  every meeting that has both found 7 of 1,030 where the packet is the wrong
  one (a "Please refer to the agenda document" placeholder, or crossed
  papers); those are corrected per event in `agenda_documents`. The price is
  size: packets carry every attachment and reach about 300 MB.

That per-meeting detail call is the whole cost of a council, which is why
subclasses restrict `meeting_types` to council and planning bodies on
tenants that publish dozens of other committees.

**Resolve is rarely a council's whole record.** A tenant starts when the
council moved to Resolve, and what came before stays wherever the council
kept it; some councils also left a body behind (Burnside's assessment panel
is still on its own website). A subclass sets `resolve_from` to the day its
Resolve record starts and returns the rest from `other_meetings`.

**A failed listing raises.** The listing is the only way to learn a tenant's
meetings, so a council blocked or down from the runner must not return an
empty list: production counts that as a council that worked (AGENTS.md, on
`okCouncils`). Only the extra 'future' query is allowed to fail quietly.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Optional

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

API_ROOT = "https://api.resolve.red/public"

# The body of DocPreview's 302 when the document exists: ASP.NET's stock
# "Object moved" page, linking the signed blob. The extension is matched
# case-insensitively because older uploads are stored as `.PDF`.
_PDF_REDIRECT = re.compile(
    r'Object moved to <a href="https://[^"]+\.blob\.core\.windows\.net/[^"?]+\.pdf\?',
    re.IGNORECASE,
)
_ANY_REDIRECT = re.compile(r"Object moved to <a href=", re.IGNORECASE)

# DocPreview's query flag for each document, and the detail call's field.
_FLAGS = {"agenda": "", "packet": "&p=1", "minutes": "&m=1"}
_FILE_FIELDS = {
    "agenda": "agendaFile",
    "packet": "packetFile",
    "minutes": "minutesFile",
}

# Meeting types are re-created for each council term at some tenants
# ("Council Meeting 2024-2028", "2021 - 2024 Council Meeting"), so the term
# is dropped and a meeting keeps one name across elections.
_TERM = re.compile(r"\s*\b(19|20)\d{2}\s*-\s*(19|20)\d{2}\b\s*")

# The meeting type does not distinguish a special meeting from an ordinary
# one at any tenant seen so far; only the free-typed event name does.
_SPECIAL = re.compile(r"\b(extraordinary|special)\b", re.IGNORECASE)

# Tenants mark a cancelled meeting only by prefixing its free-typed name:
# "CANCELLED - Operations Committee - 19 October 2026", "Cancelled - Council
# Assessment Panel 16 September 2026".
_CANCELLED = re.compile(r"\s*cancell?ed\b", re.IGNORECASE)


class SoleSourceFailed(RuntimeError):
    """A second source failed for a body Resolve does not carry.

    `ResolveScraper.scraper` keeps Resolve's meetings when `other_meetings`
    fails, because those are usually older years of bodies that moved. This
    is the exception: the body is not on Resolve, so its meetings for the
    wanted years exist nowhere else, and the council fails rather than drop
    them quietly."""


class ResolveScraper(BaseScraper):
    """Base class for a Resolve tenant. A subclass sets `tenant` and calls
    `super().__init__(council_name, state)`."""

    #: The portal subdomain, which is also the `X-RESOLVE-CLIENT` value.
    tenant: str = ""

    #: Matched against `meetingTypeName` with the council term stripped
    #: (see `_TERM`), so an anchored pattern survives the next election's
    #: "Council Meeting 2026-2030"; None keeps every type. A pattern rather
    #: than the tenant's type ids, because ids change when a tenant re-creates
    #: its types for a new council term.
    meeting_types: Optional[re.Pattern] = None

    #: Corrections to a tenant's type names, applied after the term is
    #: stripped. Some arrive misspelt or cut off at 50 characters.
    meeting_type_names: dict[str, str] = {}

    #: Emit the packet (agenda with reports and attachments) as `agenda_url`
    #: where the meeting has one, falling back to the bare agenda. See the
    #: module docstring for why; False flips the preference.
    prefer_packet: bool = True

    #: Event id -> "agenda" or "packet", for the meetings where the
    #: preference picks the wrong document, or None where neither holds the
    #: agenda (a cover sheet), leaving the record with its minutes only.
    #: Found by comparing the two documents' sizes, which the scraper cannot
    #: afford to do itself; each entry needs a comment saying what is wrong.
    agenda_documents: dict[int, Optional[str]] = {}

    #: Also emit past events the API marks unpublished, when DocPreview still
    #: serves their PDFs. Only for a tenant whose public /web/ portal lists
    #: those events with their documents; on others the council has hidden
    #: them, and DocPreview is a side door.
    include_unpublished: bool = False

    #: Event ids to drop, for council data errors such as one meeting entered
    #: twice. Each entry needs a comment saying what is wrong with it.
    skip_events: frozenset[int] = frozenset()

    #: Event id -> the meeting's real date (ISO), where the council entered
    #: the wrong one. The time of day is kept from `eventDate`.
    event_dates: dict[int, str] = {}

    #: The first day the council's record is on Resolve. Events dated
    #: earlier are dropped before their detail call, for a council whose
    #: tenant also holds copies of meetings it publishes elsewhere, and years
    #: before it are not listed at all. None keeps everything the tenant has.
    resolve_from: Optional[datetime.date] = None

    # Detail calls that failed in the current run; see `_resolve_meetings`.
    _detail_failures: int = 0

    def __init__(self, council_name: str, state: str):
        super().__init__(council_name, state, self.portal_url)

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        """Meetings in `wanted` years that the council publishes somewhere
        other than Resolve: its archive from before `resolve_from`, or a body
        it never moved. A fetch failure should raise; see `scraper`."""
        return []

    def before_resolve(self, wanted: set[int]) -> list[int]:
        """The wanted years that reach back before `resolve_from`, oldest
        first: the years an archive of pre-Resolve meetings must be read
        for. Production asks for one year, so once a council has been on
        Resolve for a full year this is empty and the archive costs
        nothing."""
        if not self.resolve_from:
            return []
        return sorted(year for year in wanted if year <= self.resolve_from.year)

    @property
    def portal_url(self) -> str:
        return f"https://{self.tenant}.resolve.red/portal/"

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        results = self._resolve_meetings(wanted)

        # A second source failing must not throw away what Resolve returned,
        # and must not hide behind it either: when it was the only source
        # with meetings in range, its failure is the council's.
        try:
            others = self.other_meetings(wanted)
        except SoleSourceFailed:
            raise
        except Exception as e:
            if not results:
                raise
            self.logger.warning(
                f"{self.council_name}: returning {len(results)} Resolve "
                f"meeting(s) without the council's other source, which failed: {e}"
            )
            others = []
        if others:
            # Interleaved by date. Resolve's own meetings otherwise keep the
            # tenant's order, which `event_dates` corrections can leave out
            # of date order.
            results = sorted(results + others, key=lambda r: r.date)

        if results:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results

    def _resolve_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        if self.resolve_from:
            wanted = {year for year in wanted if year >= self.resolve_from.year}
            if not wanted:
                return []
        events = self._events(wanted)

        today = clock.today()
        self._detail_failures = 0
        results = []
        for event in sorted(events.values(), key=lambda e: e["eventDate"]):
            record = self._record(event, today)
            if record:
                results.append(record)

        if not results and self._detail_failures:
            # Every published meeting's detail call failed: the tenant is
            # unreachable, not empty.
            raise RuntimeError(
                f"{self.council_name}: {self._detail_failures} Resolve event "
                f"detail call(s) failed and no meeting was read"
            )
        if not results:
            self.logger.warning(
                f"{self.council_name}: Resolve tenant {self.tenant!r} listed "
                f"{len(events)} event(s) in {sorted(wanted)} but none with "
                f"published documents"
            )
        return results

    # --- listing ---------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _events(self, wanted: set[int]) -> dict[int, dict]:
        """Every listed event dated in a wanted year, keyed by event id."""
        events: dict[int, dict] = {}

        # The date range is the fetch bound, so production—which asks for
        # one year—pages through that year alone. A non-contiguous filter
        # becomes one range per run of years rather than one wide range.
        for start, end in _year_runs(wanted):
            # In the year Resolve starts, the range starts with it, so the
            # events a council also published elsewhere are not paged
            # through only to be dropped.
            first = f"{start}-01-01"
            if self.resolve_from and self.resolve_from.year == start:
                first = self.resolve_from.isoformat()
            self._collect(
                events,
                wanted,
                f"{API_ROOT}/Events?type=past&startDate={first}"
                f"&endDate={end}-12-31",
                required=True,
            )

        # The ranged 'past' query already returns future-dated events, so
        # this normally adds nothing. It costs one request, and it is what
        # the portal itself uses for upcoming meetings, so it keeps them in
        # if the 'past' query is ever made to mean what it says.
        self._collect(events, wanted, f"{API_ROOT}/Events?type=future", required=False)
        return events

    def _collect(
        self, events: dict[int, dict], wanted: set[int], query: str, required: bool
    ):
        page = 1
        while True:
            url = f"{query}&page={page}"
            try:
                listing = json.loads(
                    self.fetcher.fetch_with_requests(
                        url, headers={"X-RESOLVE-CLIENT": self.tenant}
                    )
                )
            except Exception as e:
                if required:
                    raise RuntimeError(
                        f"{self.council_name}: could not read Resolve listing {url}"
                    ) from e
                self.logger.warning(
                    f"{self.council_name}: could not read Resolve listing {url}: {e}"
                )
                return

            for event in listing.get("results") or []:
                if _year(event) in wanted:
                    events.setdefault(event["id"], event)

            if page >= (listing.get("totalPages") or 0):
                return
            page += 1

    # --- records ---------------------------------------------------------

    def _record(self, event: dict, today: datetime.date) -> Optional[ScraperReturn]:
        if self.meeting_types and not self.meeting_types.search(_type_name(event)):
            return None
        if event["id"] in self.skip_events:
            return None
        if _CANCELLED.match(event.get("name") or ""):
            # A cancelled meeting keeps its event, and the council files the
            # notice of cancellation as its packet (Mount Barker's 16
            # September 2026 panel), so it would otherwise read as a meeting
            # with an agenda. Checked before the detail call, so it is free.
            return None

        agenda_id = event.get("agendaId")
        if not agenda_id:
            return None

        when = datetime.datetime.fromisoformat(event["eventDate"])
        if event["id"] in self.event_dates:
            real = datetime.date.fromisoformat(self.event_dates[event["id"]])
            when = when.replace(year=real.year, month=real.month, day=real.day)
        if self.resolve_from and when.date() < self.resolve_from:
            return None

        if event.get("isAgendaPublished"):
            documents = self._published_documents(event)
        elif self.include_unpublished and when.date() < today:
            # The detail call 404s for an unpublished event, so its documents
            # can only be learnt by asking for each one. Upcoming events are
            # left alone: an unpublished agenda before the meeting is a draft.
            documents = self._probed_documents(agenda_id)
        else:
            # Unpublished, and the portal hides it. The detail call would 404.
            return None
        if not documents:
            return None

        agenda_url = None
        if event["id"] in self.agenda_documents:
            choice = self.agenda_documents[event["id"]]
            preference = (choice,) if choice else ()
        else:
            preference = self._agenda_preference()
        for kind in preference:
            if kind in documents:
                agenda_url = self._document_url(agenda_id, _FLAGS[kind])
                break
        if not agenda_url and "minutes" not in documents:
            return None
        minutes_url = (
            self._document_url(agenda_id, _FLAGS["minutes"])
            if "minutes" in documents
            else None
        )

        return ScraperReturn(
            name=self._meeting_name(event),
            # eventDate is the council's local wall-clock time, with no
            # offset: a 7pm Willoughby meeting is "T19:00:00".
            date=when.strftime("%Y-%m-%d"),
            time=when.strftime("%I:%M %p").lstrip("0"),
            webpage_url=f"{self.portal_url}meeting/{event['id']}",
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=(event.get("eventLocation") or "").strip() or None,
        )

    def _document_url(self, agenda_id: int, flag: str = "") -> str:
        return (
            f"https://{self.tenant}.resolve.red/web/UserControls/DocPreview.aspx"
            f"?aoid={agenda_id}{flag}"
        )

    def _agenda_preference(self) -> tuple[str, str]:
        return ("packet", "agenda") if self.prefer_packet else ("agenda", "packet")

    def _published_documents(self, event: dict) -> set[str]:
        """Which of agenda, packet and minutes the detail call says exist."""
        url = f"{API_ROOT}/Events/{event['id']}"
        try:
            detail = json.loads(
                self.fetcher.fetch_with_requests(
                    url, headers={"X-RESOLVE-CLIENT": self.tenant}
                )
            )
        except Exception as e:
            # One meeting lost to a transient failure is a warning; all of
            # them is the tenant being unreachable, which `_resolve_meetings`
            # raises on.
            self._detail_failures += 1
            self.logger.warning(
                f"{self.council_name}: could not read Resolve event {url}: {e}"
            )
            return set()
        return {kind for kind, field in _FILE_FIELDS.items() if detail.get(field)}

    def _probed_documents(self, agenda_id: int) -> set[str]:
        """Which documents DocPreview serves, asked one at a time.

        Stops at the first agenda document found in order of preference, so a
        meeting costs two requests when it has the preferred one."""
        documents = set()
        for kind in self._agenda_preference():
            if self._serves_pdf(self._document_url(agenda_id, _FLAGS[kind])):
                documents.add(kind)
                break
        if self._serves_pdf(self._document_url(agenda_id, _FLAGS["minutes"])):
            documents.add("minutes")
        return documents

    def _serves_pdf(self, url: str) -> bool:
        # With redirects off, DocPreview answers a ~440-byte 302 to a blob
        # PDF when the document exists and the 1.4 KB "no file" page when it
        # does not—cheaper than following the redirect to a 50 MB PDF.
        try:
            body = self.fetcher.fetch_with_requests(url, allow_redirects=False)
        except Exception as e:
            self.logger.warning(f"{self.council_name}: could not check {url}: {e}")
            return False

        if _PDF_REDIRECT.search(body):
            return True
        if _ANY_REDIRECT.search(body):
            # A document exists but is not a PDF. The URL fields promise a
            # PDF, and nothing seen so far lands here, so say so.
            self.logger.warning(f"{self.council_name}: {url} is not a PDF; skipped")
        return False

    def _meeting_name(self, event: dict) -> str:
        type_name = _type_name(event)
        type_name = self.meeting_type_names.get(type_name, type_name)
        if not type_name:
            return (event.get("name") or "").strip()

        special = _SPECIAL.search(event.get("name") or "")
        if special and not _SPECIAL.search(type_name):
            word = special.group(1).capitalize()
            # "Ordinary Council" with "extraordinary" in the event name is an
            # Extraordinary Council meeting, not an "Extraordinary Ordinary"
            # one.
            if type_name.lower().startswith("ordinary "):
                return f"{word} {type_name[len('ordinary '):]}"
            return f"{word} {type_name}"
        return type_name


def _type_name(event: dict) -> str:
    """The event's meeting type without the council term."""
    return _TERM.sub(" ", event.get("meetingTypeName") or "").strip()


def _year(event: dict) -> Optional[int]:
    try:
        return int(event["eventDate"][:4])
    except (KeyError, TypeError, ValueError):
        return None


def _year_runs(years: set[int]) -> list[tuple[int, int]]:
    """Collapse years into contiguous (first, last) runs."""
    runs: list[tuple[int, int]] = []
    for year in sorted(years):
        if runs and year == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], year)
        else:
            runs.append((year, year))
    return runs
