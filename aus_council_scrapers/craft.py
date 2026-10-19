"""Craft CMS meeting archives, as built for South Australian councils.

Six SA councils publish meetings through Craft CMS sites built by the same
Adelaide agency (Simple, sold as "SimpleGov"): `adelaide_hills`, `barossa`,
`salisbury`, `marion`, `holdfast_bay` and `playford`. The row markup differs
from site to site, but the archive behind it is one module, and that is the
part worth sharing:

- **One filter form, read by GET.** Every site takes
  `when=custom&from=YYYY-MM-DD&to=YYYY-MM-DD` and bounds the listing to that
  range, upcoming meetings included. The dates must be ISO: the
  `DD/MM/YYYY` the date picker displays answers HTTP 500, which is why an
  earlier survey concluded Salisbury had no usable date filter.
- **One pager, by path.** Page n of a query lives at `<listing>/p<n>?<same
  query>`. Some sites never page (Adelaide Hills serves every meeting on one
  2.5 MB page), so the next page is followed only when the page links to it.
- **Documents filed by kind.** Every PDF sits under the site's asset store in
  a folder that says what it is: `.../agendas/...`, `.../minutes/...`, with
  addenda, attachments, orders of business and audio in folders of their own.
  The folder is a better witness than the link text, which is free text on
  Holdfast Bay and Barossa ("Council Agenda and Reports 9 December 2025",
  "Addendum Agenda Ordinary Council ...").

So a year costs one query, paged: production asks for a single year, and the
date range bounds what gets fetched rather than filtering afterwards.

**The fetch layer is per council, and it is measured, not guessed.** All six
sit behind AWS WAF on CloudFront. From a GitHub-hosted runner—the network
production runs on—five of them answer 202 with an empty body and
`x-amzn-waf-action: challenge` to any requests client, browser User-Agent or
not, so they need Selenium. Playford alone passes plain requests with
`BROWSER_USER_AGENT`, and sets `use_selenium = False`. Adelaide Hills'
CloudFront also rejects the `HeadlessChrome` token, so it opts into
`strip_headless_user_agent`. Barossa does too as a precaution: it was not
measured headless from the runner, and from a home IP it returns the same
meetings either way.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, NavigableString
from bs4.element import TemplateString
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# Present on every real archive page, including one with no results, and
# absent from the WAF challenge interstitial. Selenium waits for it, and a
# requests fetch without it is the challenge rather than an empty archive.
_ARCHIVE_MARKER = 'select[name="when"]'

# Only stops a runaway if a site ever starts clamping out-of-range pages to
# the last one. The largest full-history queries here, every committee since
# 2020, are 37 pages (Holdfast Bay) and 32 (Salisbury).
_MAX_PAGES = 120

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_WORDED_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_TIME = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*[ap]\.?m\.?", re.IGNORECASE)

_AGENDA_FOLDER = re.compile(r"/agendas?/", re.IGNORECASE)
_MINUTES_FOLDER = re.compile(r"/minutes?/", re.IGNORECASE)
# Not \b: filenames join words with underscores ("13_01_2020_-_minutes_-_"),
# and an underscore is a word character.
_AGENDA_WORD = re.compile(r"(?<![a-z])agendas?(?![a-z])", re.IGNORECASE)
_MINUTES_WORD = re.compile(r"(?<![a-z])minutes?(?![a-z])", re.IGNORECASE)

# The suffix Craft adds when a file is uploaded under a name already taken:
# "..._2024-10-17-004159_ogln.pdf" was uploaded at 00:41:59 on 17 October.
_UPLOAD_STAMP = re.compile(
    r"_(\d{4})-(\d{2})-(\d{2})-\d{6}_[a-z]{4}\.pdf$", re.IGNORECASE
)

# What a listing shows when nobody filled the field in.
_UNSET_VENUE = re.compile(r"^no venue set$", re.IGNORECASE)
_UNSET_TIME = re.compile(r"^12:00\s*am$", re.IGNORECASE)

# Never the paper, wherever it is filed. Holdfast Bay puts a meeting's notice
# of cancellation in its agendas folder, and Barossa posts a NO-AGENDA.pdf
# placeholder for a cancelled workshop; a meeting holding only one of them
# has nothing to publish.
_PLACEHOLDER = re.compile(r"cancel|no[\s_-]*agenda", re.IGNORECASE)

# A second document of the same kind, even inside the agendas folder.
_SECONDARY = re.compile(r"supplementar|addend", re.IGNORECASE)

# When the folder says nothing and the link text has to decide, these mark
# the companions that crowd every meeting's attachments: confidential items
# released later ("Confidential Release ... Minutes C091225"), single
# agenda items, attachments. Inside the agendas or minutes folder the same
# words are harmless ("...-Minutes-CEO-Review-Committee-with-attachment.pdf"
# is Salisbury's actual minutes), so this applies only to the fallback.
_COMPANION = re.compile(
    r"confidential|released?|attach|(?<![a-z])item(?![a-z])|supplementar|addend",
    re.IGNORECASE,
)


@dataclass
class CraftMeeting:
    """One listing row, before its documents are sorted into agenda/minutes."""

    name: str
    date: datetime.date
    time: Optional[str] = None
    location: Optional[str] = None
    #: (link text, absolute URL), in page order.
    links: list[tuple[str, str]] = field(default_factory=list)


def clean_text(element) -> str:
    """An element's visible text, whitespace collapsed.

    Text inside an HTML `<template>` counts. Salisbury wraps each meeting's
    documents row in Alpine's `<template x-if>`, and BeautifulSoup files
    strings in a template as `TemplateString`, which `get_text()` leaves out
    by default—so every Salisbury link label came back empty, and the
    label pass could never fire there.
    """
    if element is None:
        return ""
    if isinstance(element, str):
        text = element
    else:
        text = element.get_text(
            " ", strip=True, types=(NavigableString, TemplateString)
        )
    return re.sub(r"\s+", " ", text).strip()


def parse_listing_date(text: str) -> Optional[datetime.date]:
    """The meeting date as these sites write it.

    Three spellings across the six sites: `16/12/2025` (Salisbury, day
    first), `10 Dec. 2025` (Adelaide Hills) and `9 December 2025`. Parsed
    here rather than handed to dateutil, which reads `10/08/2026` month-first
    as 8 October.
    """
    match = _NUMERIC_DATE.search(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None

    match = _WORDED_DATE.search(text)
    if match:
        day, month_name, year = match.groups()
        try:
            month = datetime.datetime.strptime(month_name[:3].title(), "%b").month
            return datetime.date(int(year), month, int(day))
        except ValueError:
            return None
    return None


def parse_listing_time(text: str) -> Optional[str]:
    match = _TIME.search(text)
    return match.group().strip() if match else None


def document_links(container, base_url: str) -> list[tuple[str, str]]:
    """Every link in a row's document area, as (label, absolute URL)."""
    links = []
    for anchor in container.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        # The size ("(40.4MB PDF)") is part of the link text on every site.
        label = re.sub(r"\([^)]*\)", " ", clean_text(anchor))
        links.append((clean_text(label), urllib.parse.urljoin(base_url, href)))
    return links


def _without_cache_buster(url: str) -> str:
    """Drop the `?v=<timestamp>` Craft appends to asset URLs.

    It changes whenever a file is re-uploaded, so leaving it in makes the
    same document look like a new one to anything downstream that keys on
    the URL. The file is served the same without it.
    """
    parts = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if key != "v"
    ]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _uploaded_before(filename: str, meeting_date: Optional[datetime.date]) -> bool:
    """Whether the filename's Craft upload stamp predates the meeting."""
    match = _UPLOAD_STAMP.search(filename)
    if not match or meeting_date is None:
        return False
    try:
        uploaded = datetime.date(*(int(part) for part in match.groups()))
    except ValueError:
        return False
    return uploaded < meeting_date


def classify_document(
    label: str,
    url: str,
    by_label: bool = False,
    meeting_date: Optional[datetime.date] = None,
) -> Optional[str]:
    """`"agenda"`, `"minutes"` or None for a link in a meeting's row.

    The folder decides. With `by_label`, a PDF filed outside the agendas and
    minutes folders is judged by its link text instead. That pass exists
    because councils misfile the main paper now and then (Holdfast Bay's
    Council minutes of 22 October 2024 sit in `attachments/`), and it runs
    only for a kind the folders left empty, so a released confidential
    item can never displace the meeting's own minutes.
    """
    path = urllib.parse.urlsplit(url).path
    if not path.lower().endswith(".pdf"):
        # Marion links each meeting's audio recording beside its papers.
        return None

    filename = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    text = f"{label} {filename}"
    if _PLACEHOLDER.search(text) or _SECONDARY.search(text):
        return None

    if by_label:
        if _MINUTES_FOLDER.search(path) or _AGENDA_FOLDER.search(path):
            return None  # The folder pass already judged it.
        if _COMPANION.search(text):
            return None
        if _MINUTES_WORD.search(label) and not _AGENDA_WORD.search(label):
            return "minutes"
        if _AGENDA_WORD.search(label) and not _MINUTES_WORD.search(label):
            return "agenda"
        return None

    if _MINUTES_FOLDER.search(path):
        return "minutes"
    if _AGENDA_FOLDER.search(path):
        # One exception, for a slip that happens on the council side: the
        # minutes uploaded into the agenda slot after the meeting. Salisbury's
        # Audit and Risk Committee of 9 October 2024 and Adelaide Hills' panel
        # of 15 October 2025 both hold a minutes PDF there, and say so in the
        # filename. Combined "Agenda-and-Minutes" papers name both, and stay.
        #
        # A file Craft stamped as uploaded before the meeting cannot be its
        # minutes, whatever it is called. That keeps Playford's Ordinary
        # Council agenda of 22 October 2024, named "...-Open-Minutes" but
        # uploaded on 17 October; the two real misfilings carry no stamp.
        if (
            _MINUTES_WORD.search(filename)
            and not _AGENDA_WORD.search(filename)
            and not _uploaded_before(filename, meeting_date)
        ):
            return None
        return "agenda"
    return None


class CraftArchiveScraper(BaseScraper):
    """Shared fetch-and-page loop for the SA Craft meeting archives.

    A subclass supplies `listing_url` and `parse_meetings`, and sets
    `use_selenium` / `strip_headless_user_agent` / `user_agent` to whatever
    that council's WAF was measured to need.
    """

    #: The archive page, without query or `/pN` suffix.
    listing_url: str = ""

    #: Whether the listing must be loaded in a browser to clear the WAF.
    use_selenium: bool = True

    #: A folder whose PDF is the agenda when the agendas folder holds none.
    #: Adelaide Hills sometimes files the whole agenda as the order of
    #: business; see its module.
    fallback_agenda_folder: Optional[re.Pattern] = None

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page_url(self, page: int, first_year: int, last_year: int) -> str:
        path = self.listing_url if page == 1 else f"{self.listing_url}/p{page}"
        query = urllib.parse.urlencode(
            {
                "when": "custom",
                "from": f"{first_year}-01-01",
                "to": f"{last_year}-12-31",
            }
        )
        return f"{path}?{query}"

    def _fetch(self, url: str) -> BeautifulSoup:
        """Load one archive page, retrying once.

        The WAF challenge reloads the page once it has issued a token, so the
        browser waits for the filter form rather than reading the source
        straight after `get()`. A page that never shows the form is a failed
        fetch, not an empty archive: the AWS challenge answers 202 with an
        empty body, which `fetch_with_requests` returns without raising.
        """
        last_error: Optional[BaseException] = None
        for attempt in range(2):
            try:
                if self.use_selenium:
                    html = self.fetcher.fetch_with_selenium(
                        url,
                        wait_time=30,
                        wait_condition=EC.presence_of_element_located(
                            (By.CSS_SELECTOR, _ARCHIVE_MARKER)
                        ),
                    )
                else:
                    html = self.fetcher.fetch_with_requests(url)
                soup = BeautifulSoup(html, "html.parser")
                if soup.select_one(_ARCHIVE_MARKER) is None:
                    raise RuntimeError(
                        f"{url} returned no meeting archive ({len(html)} bytes); "
                        f"most likely the AWS WAF challenge rather than a page"
                    )
                return soup
            except Exception as error:
                # CassetteMiss is a BaseException, so a missing recording
                # still surfaces instead of being retried.
                last_error = error
                self.logger.warning(
                    f"{type(error).__name__} loading {url} "
                    f"(attempt {attempt + 1}/2): {error}"
                )
                if self.use_selenium:
                    self.fetcher.restart_driver()
        raise last_error

    @staticmethod
    def _links_to_page(soup: BeautifulSoup, page: int) -> bool:
        suffix = f"/p{page}"
        return any(
            urllib.parse.urlsplit(anchor["href"]).path.rstrip("/").endswith(suffix)
            for anchor in soup.find_all("a", href=True)
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        first_year, last_year = min(wanted), max(wanted)

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        used_urls: set[str] = set()
        undocumented = 0

        for page in range(1, _MAX_PAGES + 1):
            soup = self._fetch(self._page_url(page, first_year, last_year))
            meetings = self.parse_meetings(soup)
            if page == 1 and not meetings:
                self.logger.warning(
                    f"{self.council_name}: the archive listed no meetings for "
                    f"{first_year}-{last_year}; if the council has met, the "
                    f"row markup has changed"
                )

            for meeting in meetings:
                if meeting.date.year not in wanted:
                    continue
                record = self._to_return(meeting)
                if record is None:
                    # Nearly always a scheduled meeting whose papers are not
                    # up yet, or one cancelled with only a notice to show.
                    undocumented += 1
                    continue
                # Salisbury repeats its upcoming-meetings panel on every page
                # of the query, so the same meeting arrives more than once.
                key = (record.name, record.date, record.agenda_url, record.minutes_url)
                if key in seen:
                    continue
                seen.add(key)

                # One PDF cannot be the paper of two different meetings, but
                # it can be uploaded into both: Holdfast Bay's Executive
                # Committee of 23 January 2024 holds that night's Council
                # agenda in its agenda slot. The meeting listed first keeps
                # the document. If nothing is left, there is nothing to emit.
                for field_name in ("agenda_url", "minutes_url"):
                    url = getattr(record, field_name)
                    if url and url in used_urls:
                        self.logger.info(
                            f"{record.name} {record.date}: {field_name} {url} "
                            f"already belongs to another meeting; dropped"
                        )
                        setattr(record, field_name, None)
                if not (record.agenda_url or record.minutes_url):
                    undocumented += 1
                    continue
                record.download_url = record.agenda_url or record.minutes_url
                used_urls.update(
                    u for u in (record.agenda_url, record.minutes_url) if u
                )
                results.append(record)

            if not self._links_to_page(soup, page + 1):
                break
        else:
            self.logger.warning(
                f"Stopped at the {_MAX_PAGES}-page cap; the archive may hold "
                f"more meetings than were collected."
            )

        if not results:
            message = (
                f"{self.council_name}: no meetings with papers for "
                f"{first_year}-{last_year}"
            )
            # Every one of these councils meets at least monthly and posts
            # papers before the meeting, so a range holding three months of
            # the past with nothing in it means the row or document markup
            # has changed. Raise, so production reports the council as
            # failed rather than as fine with 0 meetings. A range that is
            # nearly all future (a new year's first weeks) only warns.
            if clock.today() - datetime.date(first_year, 1, 1) > datetime.timedelta(
                days=90
            ):
                raise RuntimeError(
                    message + "; the archive markup has probably changed"
                )
            self.logger.warning(message)
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings "
                f"({undocumented} listed with no agenda or minutes yet)"
            )
        return results

    def _to_return(self, meeting: CraftMeeting) -> Optional[ScraperReturn]:
        papers: dict[str, str] = {}
        # Folders first; link text only for a kind the folders left empty.
        # Within a pass the first of each kind wins, since the main paper is
        # listed before anything else of its kind.
        for by_label in (False, True):
            for label, url in meeting.links:
                kind = classify_document(
                    label, url, by_label=by_label, meeting_date=meeting.date
                )
                if kind and kind not in papers:
                    papers[kind] = _without_cache_buster(url)

        if "agenda" not in papers and self.fallback_agenda_folder is not None:
            for label, url in meeting.links:
                if self._is_fallback_agenda(label, url):
                    papers["agenda"] = _without_cache_buster(url)
                    break

        agenda_url = papers.get("agenda")
        minutes_url = papers.get("minutes")
        if not agenda_url and not minutes_url:
            return None

        # The meetings module prints "No venue set" and "12:00 am" for fields
        # left blank. Nobody meets at midnight.
        location = meeting.location or None
        if location and _UNSET_VENUE.match(location):
            location = None
        time = meeting.time
        if time and _UNSET_TIME.match(time):
            time = None

        return ScraperReturn(
            name=meeting.name or self.default_name,
            date=meeting.date.isoformat(),
            time=time,
            webpage_url=self.listing_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location,
        )

    def _is_fallback_agenda(self, label: str, url: str) -> bool:
        path = urllib.parse.urlsplit(url).path
        if not path.lower().endswith(".pdf"):
            return False
        if not self.fallback_agenda_folder.search(path):
            return False
        filename = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        text = f"{label} {filename}"
        if _PLACEHOLDER.search(text) or _SECONDARY.search(text):
            return False
        # The same guard as the agendas folder: minutes are never the agenda.
        return not (
            _MINUTES_WORD.search(filename) and not _AGENDA_WORD.search(filename)
        )


class CraftMeetingsModuleScraper(CraftArchiveScraper):
    """Adelaide Hills, Barossa and Salisbury: the "meetings module" layout.

    A table with an upcoming panel and a past panel, each row carrying
    `data-th="Date / Time"`, `"Location"`, `"Meeting Type"` and
    `"Documents"` cells. The documents are in a second row that the first
    one's toggle button names through `aria-labelledby`. On Salisbury that
    second row is wrapped in an Alpine `<template x-if>`, which is still in
    the HTML, so no expanding is needed.
    """

    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        panels = {
            element["aria-labelledby"]: element
            for element in soup.find_all(attrs={"aria-labelledby": True})
        }

        meetings = []
        for cell in soup.select('td[data-th="Date / Time"]'):
            row = cell.find_parent("tr")
            when = clean_text(cell)
            date = parse_listing_date(when)
            if date is None:
                self.logger.warning(f"No date in listing row: {when!r}")
                continue

            button = row.select_one("button[id]")
            panel = panels.get(button["id"]) if button else None

            meetings.append(
                CraftMeeting(
                    name=clean_text(row.select_one('td[data-th="Meeting Type"]')),
                    date=date,
                    time=parse_listing_time(when),
                    location=clean_text(row.select_one('td[data-th="Location"]')),
                    links=document_links(panel, self.listing_url) if panel else [],
                )
            )
        return meetings
