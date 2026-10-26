"""Councils publishing through Civica Modern.Gov (ModernGov).

Modern.Gov is a committee-management product sold mostly to UK councils; in
Australia it runs `meetings.cityofadelaide.com.au` and
`meetings.cityofsydney.nsw.gov.au`. Its public pages are plain server-rendered
HTML, so this needs no browser—but nothing on a listing page links a
document. The shape of a scrape is:

1. **One listing per committee per year**—`ieListMeetings.aspx`. Each row is
   a meeting link plus a short status suffix the platform writes itself:
   `"- Agenda, Minutes"`, `"- Agenda, Draft Minutes; Special"`,
   `"- CANCELLED"`, `"- Documents available"` (legacy meetings), or nothing
   at all for a meeting not yet papered. That suffix is what keeps the cost
   down: a row with no documents is never fetched.
2. **One page per meeting** for the documents themselves. There is no listing,
   feed or web-service call that carries document URLs—Sydney's
   `mgWebService.asmx` is enabled, but `GetMeetings` returns only ids, dates
   and status, and `GetMeeting` returns item metadata without the agenda or
   minutes files. Adelaide's web service is 404. So the per-meeting page is
   the irreducible cost, and the committee allowlist on each subclass is what
   bounds it.

Three platform behaviours that look like bugs in our code if you do not know
them:

- **`?Year=<current year>` is ignored on a GET.** It returns the default
  "around now" window of fifteen meetings, not the year.
  Adelaide's `?Year=2026` silently dropped January to May and the December
  meeting. Every other year honours the GET. Posting the year-select form
  works for every year, current included, so listings are always POSTed.
- **A year the committee's dropdown does not offer returns a different
  year.** Asking Sydney's Local Planning Panel for 2027 answers with 2026's
  meetings, and Adelaide's planning committee (created 2023) answers 2020
  with 2023. Rows are therefore kept only when their own date is in the year
  asked for, and the dropdown read off the first response decides which other
  years are worth requesting at all.
- **Two generations of meeting page.** Meetings from before the council
  migrated onto Modern.Gov proper (Adelaide until early 2022, Sydney until
  April 2018) are `CeListDocuments.aspx` pages holding a bare list of
  uploaded PDFs under `Data/`. Their links must be followed exactly as the
  listing gives them: rebuilding one as `ieListDocuments.aspx` redirects to a
  login page.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# The listing link text is "24 Nov 2026\xa05.30 pm"; a few legacy meetings
# carry no time at all.
_ROW_WHEN = re.compile(
    r"(?P<date>\d{1,2} [A-Za-z]{3} \d{4})"
    r"(?:\s+(?P<hour>\d{1,2})\.(?P<minute>\d{2})\s*(?P<ampm>[ap]m))?",
    re.IGNORECASE,
)

# What the row suffix says when there is something to fetch. "Documents
# available" is how legacy meetings are flagged; "Decisions" appears on some
# Modern.Gov sites alongside or instead of minutes.
_HAS_DOCUMENTS = re.compile(
    r"\b(agenda|minutes|documents available|decisions)\b", re.IGNORECASE
)

# A meeting the platform marks POSTPONED or CANCELLED keeps whatever was
# uploaded for it, so its row can still say "Agenda". Adelaide's special
# meeting of 11 April 2025 reads "Agenda, POSTPONED; Special (adjourned to 14
# April 2025 at 7:00 pm)": it never sat, and the reconvened meeting of 15 April
# says on its own page that it used that agenda. Such a row is skipped unless
# it also has minutes—the special meeting of 25 March 2025, also marked
# POSTPONED, did convene, to adjourn itself, and has minutes saying so.
_NOT_HELD = re.compile(r"^(postponed|cancell?ed)$", re.IGNORECASE)
_HAS_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)

# Meeting statuses worth carrying into the name. They arrive bare
# ("Special") or annotated ("Special (reconvened from 14 April 2025 - 7:00
# pm)"), so match the leading word. "Cancelled" and "Postponed" never reach
# the name because such a meeting is skipped (see _NOT_HELD); anything else the
# platform writes ("Continuation of 14 December 2020") is a note, not a
# meeting type.
_QUALIFIER = re.compile(r"^(special|extraordinary)\b", re.IGNORECASE)

# On a current-generation page, the meeting's own documents are the first
# block of links (div.mgLinks), and the platform labels each with a title
# attribute naming the document type—far more stable than the link text,
# which councils edit. The agenda is the frontsheet: the agenda itself, a few
# pages listing every item. The "reports pack" is the agenda with every report
# bound in—routinely hundreds of pages, 307 MB for one Sydney planning
# meeting—and is usually one extra request away behind mgChooseDocPack.aspx,
# so it is only a fallback for a meeting that has no frontsheet. The upshot:
# a current-generation agenda_url is the item list (item titles, including DA
# addresses) without report text, while a legacy one (Adelaide before 2022) is
# the whole agenda with reports bound in, because that is all those pages hold.
_AGENDA_TITLE = re.compile(r"^Link to agenda frontsheet pdf file$", re.IGNORECASE)
_PACK_TITLE = re.compile(
    r"^Link to agenda reports\s+document pack pdf file$", re.IGNORECASE
)
_MINUTES_TITLE = re.compile(
    r"^Link to printed (draft )?minutes pdf file$", re.IGNORECASE
)
# The fallback for minutes uploaded as a plain supporting document, matched on
# link text because such links carry no title. div.mgLinks also holds
# per-item documents on Sydney's pages ("Item 3.1 - Minute by the Lord Mayor -
# ..."), and a text such as "Information Relevant To Item 4 - Minutes of the
# ... Committee" must not become a meeting's minutes. So "Minutes" has to be
# in the first segment of the text, before any dash, and that segment must not
# be about an item.
_MINUTES_TEXT = re.compile(
    r"^(?!(?:item|information)\b)[^-–—:]*\bminutes\b", re.IGNORECASE
)

# Legacy pages label documents "<Body> - Agenda", "Council Meeting - Agenda
# without conf", "Council Special Meeting - Minutes"—and also
# "Council Special Meeting - Agenda - Item 4.1 - Distributed Separately",
# which is one report, not the agenda. So the document type has to be the
# *last* segment of the label, after any trailing date ("Minutes - 19 March
# 2018"); that also keeps out agenda items such as "Confirmation of Minutes".
_LABEL_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_LEGACY_KIND = re.compile(
    r"^(?P<kind>agenda|minutes)(?:\s+without\s+conf\w*)?$", re.IGNORECASE
)
_LEGACY_DATE = re.compile(r"^\d{1,2}(?:st|nd|rd|th)? [A-Za-z]+ \d{4}$")

# The uploaded file's own name, which on Adelaide's legacy pages is more
# reliable than the label: for the special meeting of 16 November 2021 the
# label "Council - Agenda" links "Council Special Meeting - Minutes - 16
# November 2021.pdf", and the PDFs say the filenames are right. The filename
# is also the only place a legacy special meeting says it was one—its
# listing row says just "Documents available".
_FILENAME_KIND = re.compile(r"\b(agenda|minutes)\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\b(special|extraordinary)\b", re.IGNORECASE)

# Document paths are served with literal spaces in them ("documents/g1299/
# Agenda frontsheet 11th-Aug-2026 18.00 Council.pdf?T=0"). Percent-encode
# those, and anything non-ASCII, but leave existing escapes ("DF=30%2f12%2f
# 2020") and URL syntax alone.
_URL_SAFE = "/:?&=%#;,+@!$'()*~[]"


class ModernGovScraper(BaseScraper):
    """A Modern.Gov site, restricted to the committees a subclass names.

    Set `committees` on the subclass to `{committee_id: name}`. The id is the
    `CId` in the site's own URLs; the name is what meetings are called (with
    "Meeting" appended, and "Ordinary" for a plain Council meeting).
    """

    committees: dict[int, str] = {}

    def __init__(self, council_name: str, state: str, base_url: str):
        super().__init__(council_name, state, base_url.rstrip("/"))

    # --- years ------------------------------------------------------------

    def _wanted_years(self) -> list[int]:
        """The years to list, current year first.

        The first listing fetched for a committee also tells us which years
        its dropdown offers, so it should be one that is surely offered: an
        unoffered year answers with some other year's meetings, which is a
        request spent on nothing.
        """
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            years = set(years_filter)
        else:
            years = set(range(EARLIEST_YEAR, clock.current_year() + 3))
        this_year = clock.current_year()
        return sorted(years, key=lambda year: (year != this_year, -year))

    # --- listing ----------------------------------------------------------

    def _listing(self, committee_id: int, year: int) -> str:
        # POST, not GET: see the module docstring—a GET for the current
        # year returns a fifteen-meeting window instead of the year.
        return self.fetcher.fetch_with_requests(
            f"{self.base_url}/ieListMeetings.aspx",
            method="POST",
            data={
                "YearSelect": str(year),
                "hCommitteeId": str(committee_id),
                "hCategoryId": "0",
                "IsInfo": "0",
                "MD": "ielistmeetings",
                "Submit": "Go",
            },
        )

    @staticmethod
    def _offered_years(soup: BeautifulSoup) -> set[int]:
        select = soup.find("select", id="YearSelect")
        if not select:
            return set()
        return {
            int(option["value"])
            for option in select.find_all("option")
            if option.get("value", "").isdigit() and option["value"] != "0"
        }

    def _parse_listing(self, html: str, year: int) -> list[dict]:
        """Meetings in `year` that the listing says have documents."""
        soup = BeautifulSoup(html, "html.parser")
        meetings = []

        for link in soup.find_all("a", class_="mgMeetingTableLnk", href=True):
            when = _ROW_WHEN.search(link.get_text(" ", strip=True))
            if not when:
                self.logger.warning(
                    f"Unreadable meeting date {link.get_text(strip=True)!r}"
                )
                continue

            date = datetime.datetime.strptime(when["date"], "%d %b %Y").date()
            if date.year != year:
                # The fallback year a committee's listing answers with when
                # the year asked for is not in its dropdown.
                continue

            row = link.find_parent("li")
            suffix = row.get_text(" ", strip=True) if row else ""
            suffix = suffix[len(link.get_text(" ", strip=True)) :].strip(" -")
            parts = [part.strip() for part in suffix.split(";") if part.strip()]

            if not any(_HAS_DOCUMENTS.search(part) for part in parts):
                continue  # not yet papered, cancelled, or a bare note

            statuses = [word.strip() for part in parts for word in part.split(",")]
            if any(_NOT_HELD.match(word) for word in statuses) and not any(
                _HAS_MINUTES.search(word) for word in statuses
            ):
                continue  # postponed or cancelled, and never convened

            qualifier = next(
                (m[1].capitalize() for part in parts if (m := _QUALIFIER.match(part))),
                None,
            )

            time = None
            if when["hour"]:
                time = f"{int(when['hour'])}:{when['minute']} {when['ampm'].upper()}"

            meetings.append(
                {
                    "url": self._absolute(link["href"]),
                    "date": date.isoformat(),
                    "time": time,
                    "qualifier": qualifier,
                }
            )

        return meetings

    # --- meeting page -----------------------------------------------------

    def _absolute(self, href: str) -> str:
        url = urllib.parse.urljoin(f"{self.base_url}/", href.strip())
        return urllib.parse.quote(url, safe=_URL_SAFE)

    def _documents(self, html: str) -> dict:
        """The agenda, minutes and venue on a meeting page.

        Also `qualifier` for a legacy page, where it is not in the listing.
        """
        soup = BeautifulSoup(html, "html.parser")
        legacy = soup.find(id="mgLegacyDocList")
        if legacy is not None:
            return self._legacy_documents(legacy)

        agenda = pack = minutes = minutes_fallback = None
        links = soup.select("div.mgLinks a[href]")
        for link in links:
            title = (link.get("title") or "").strip()
            if agenda is None and _AGENDA_TITLE.match(title):
                agenda = self._absolute(link["href"])
            elif pack is None and _PACK_TITLE.match(title):
                pack = self._absolute(link["href"])
            elif minutes is None and _MINUTES_TITLE.match(title):
                minutes = self._absolute(link["href"])
            elif (
                minutes_fallback is None
                and not title
                and _MINUTES_TEXT.match(link.get_text(" ", strip=True))
            ):
                # Adelaide occasionally uploads the minutes as a plain
                # supporting document rather than publishing them through the
                # minutes workflow ("Public Council Minutes - 12 July 2022",
                # behind mgChooseMDocPack.aspx, which redirects to the PDF).
                # Only meeting-level links are looked at here; agenda items
                # such as "Confirmation of Minutes" live in the item table.
                minutes_fallback = self._absolute(link["href"])

        return {
            "agenda": agenda or pack,
            "minutes": minutes or minutes_fallback,
            "location": self._venue(soup),
            "qualifier": None,
        }

    def _legacy_documents(self, block) -> dict:
        found: dict[str, str] = {}
        qualifier = None
        for link in block.find_all("a", href=True):
            label = link.get_text(" ", strip=True)
            segments = _LABEL_SEPARATOR.split(label)
            while len(segments) > 1 and _LEGACY_DATE.match(segments[-1]):
                segments.pop()
            match = _LEGACY_KIND.match(segments[-1])
            if not match:
                continue

            kind = match["kind"].lower()
            filename = urllib.parse.unquote(link["href"]).rsplit("/", 1)[-1]
            named = {word.lower() for word in _FILENAME_KIND.findall(filename)}
            if len(named) == 1:
                kind = named.pop()

            found.setdefault(kind, self._absolute(link["href"]))
            special = _SPECIAL.search(f"{label} {filename}")
            qualifier = qualifier or (special[1].capitalize() if special else None)

        return {
            "agenda": found.get("agenda"),
            "minutes": found.get("minutes"),
            "location": None,
            "qualifier": qualifier,
        }

    @staticmethod
    def _venue(soup: BeautifulSoup) -> Optional[str]:
        for label in soup.select("div.mgContent span.mgLabel"):
            if label.get_text(strip=True).lower() in ("venue:", "proposed venue:"):
                paragraph = label.find_parent("p")
                text = paragraph.get_text(" ", strip=True) if paragraph else ""
                text = text[len(label.get_text(" ", strip=True)) :].strip()
                return text or None
        return None

    # --- naming -----------------------------------------------------------

    @staticmethod
    def _meeting_name(committee: str, qualifier: Optional[str]) -> str:
        if committee == "Council":
            return f"{qualifier or 'Ordinary'} Council Meeting"
        name = committee if committee.endswith("Meeting") else f"{committee} Meeting"
        return f"{qualifier} {name}" if qualifier else name

    # --- scrape -----------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results: list[ScraperReturn] = []
        seen: set[str] = set()
        # Fetch failures are tolerated one at a time, but if every listing
        # raised, an empty result would reach production as a council that
        # ran fine and had no meetings. Re-raise instead so it is reported as
        # failed.
        listings_tried = 0
        last_listing_error: Optional[Exception] = None
        listings_failed = 0
        pages_failed = 0
        last_page_error: Optional[Exception] = None

        for committee_id, committee in self.committees.items():
            offered: Optional[set[int]] = None

            for year in self._wanted_years():
                if offered and year not in offered:
                    continue
                listings_tried += 1
                try:
                    html = self._listing(committee_id, year)
                except Exception as e:
                    listings_failed += 1
                    last_listing_error = e
                    self.logger.warning(
                        f"Could not list {committee} meetings for {year}: {e}"
                    )
                    continue

                if offered is None:
                    offered = self._offered_years(BeautifulSoup(html, "html.parser"))
                    if not offered:
                        # Every real listing carries the year dropdown, so a
                        # page without one is an error or login page that
                        # would otherwise just look like a quiet committee.
                        self.logger.warning(
                            f"{committee} (CId {committee_id}) listing has no "
                            f"year selector—is this still a Modern.Gov listing?"
                        )

                for meeting in self._parse_listing(html, year):
                    if meeting["url"] in seen:
                        continue
                    seen.add(meeting["url"])

                    try:
                        page = self.fetcher.fetch_with_requests(meeting["url"])
                    except Exception as e:
                        self.logger.warning(f"Could not read {meeting['url']}: {e}")
                        pages_failed += 1
                        last_page_error = e
                        continue

                    documents = self._documents(page)
                    agenda_url = documents["agenda"]
                    minutes_url = documents["minutes"]
                    if not agenda_url and not minutes_url:
                        # Flagged as having documents, but none of them is an
                        # agenda or minutes—a notice of meeting on its own.
                        continue

                    results.append(
                        ScraperReturn(
                            name=self._meeting_name(
                                committee,
                                meeting["qualifier"] or documents["qualifier"],
                            ),
                            date=meeting["date"],
                            time=meeting["time"],
                            webpage_url=meeting["url"],
                            agenda_url=agenda_url,
                            minutes_url=minutes_url,
                            download_url=agenda_url or minutes_url,
                            location=documents["location"],
                        )
                    )

        if listings_tried and listings_failed == listings_tried:
            raise RuntimeError(
                f"{self.council_name}: all {listings_tried} Modern.Gov listing "
                f"requests failed"
            ) from last_listing_error

        if not results and pages_failed:
            # The listings loaded but no meeting page did: documents are only
            # on those pages, so the site is unreachable, not empty.
            raise RuntimeError(
                f"{self.council_name}: {pages_failed} Modern.Gov meeting page "
                f"request(s) failed and no meeting was read"
            ) from last_page_error

        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
