"""Councils on Kentico sites built by Alyka, the Perth web agency.

Six Perth councils publish their agendas and minutes through Alyka builds, and
every one of them renders the listing client-side: the HTML page is an empty
template plus a handful of hidden inputs, and the rows arrive from a search
endpoint afterwards. Two request protocols sit underneath, and they are the
part worth sharing. What comes back is different at every council—one
record per meeting at Stirling, per document at Melville and Rockingham, a
council-specific HTML fragment at the other three—so parsing stays in the
subclasses.

`KsearchScraper`—Kendo `aw_ksearch.js` (melville, rockingham, stirling)
    POST ``{take, skip, page, pageSize}`` to the endpoint named by
    ``input#searchapi``. The filters do not go in the body: they travel as two
    JSON-encoded request *headers*. ``SearchParam`` is built from every
    ``input[data-searchparam]`` (classname, search index, sometimes a node
    path), and without it the server answers 500. ``SearchFilter`` carries the
    user's choices—a year, a meeting type—in the shape the page's
    multiselects produce. The response is ``{Data: [...], Total}``.

`PageTypeListingScraper`—`aw_pagetypelisting.js` (kwinana, joondalup)
    POST ``{SI, OB, Q, PS, FS, PG, PR, IncludeFirst}`` to the endpoint named by
    ``div#pageTypeListing[data-api]``. ``PR`` is a list built from every
    ``[data-filter-item]`` in that div: hidden text inputs name the content
    class and the server-side template, checkbox groups carry year and meeting
    type. Leave the hidden ones out and the server returns an empty fragment.
    The response is ``{htmlResult: "<rows>"}``.

Both read their parameters from the live page rather than hard-coding them.
The hidden inputs are what decides which content class and template the
server renders, so copying today's values into code would work right up until
the council's next deploy renamed one—and then return nothing, quietly.
"""

from __future__ import annotations

import calendar
import datetime
import difflib
import json
import re
import urllib.parse
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# --------------------------------------------------------------------------
# Shared parsing helpers
# --------------------------------------------------------------------------

_MONTH_NAMES = [name.lower() for name in calendar.month_name]

# "9 September 2020", "8 & 9 December 2020", "15, 22 & 29 September 2020".
# A meeting adjourned across several nights is dated by its first.
_DAY_MONTH_YEAR = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*(?:,|&|and)\s*\d{1,2}(?:st|nd|rd|th)?)*"
    r"\s+(?P<month>[A-Za-z]{3,10})\.?,?\s+(?P<year>\d{4})\b"
)
# "February 2, 2026", "February, 12 2020" and "October 14 ,2026"—all three
# are in Swan's headings.
_MONTH_DAY_YEAR = re.compile(
    r"\b(?P<month>[A-Za-z]{3,10})\.?\s*,?\s*(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*,?\s*(?P<year>\d{4})\b"
)
_MONTH_YEAR = re.compile(r"\b(?P<month>[A-Za-z]{3,10})\.?,?\s+(?P<year>\d{4})\b")


def _month_number(word: str) -> Optional[int]:
    """A month from its name, tolerating the typos these sites carry.

    "Decemeber", "Febraury" and "Septembe" all appear in titles, so a word
    counts as a month when it abbreviates one ("Sept") or is a near-miss
    spelling of one. "Marshall" is neither, though it starts like March, so
    "Marshall 12 2026" in an address is not a date.
    """
    word = word.lower()
    for number, name in enumerate(_MONTH_NAMES):
        if not name:
            continue
        if len(word) >= 3 and name.startswith(word):
            return number
        if difflib.SequenceMatcher(None, word, name).ratio() >= 0.8:
            return number
    return None


def find_date(text: str) -> Optional[tuple[datetime.date, tuple[int, int]]]:
    """The first meeting date in ``text``, and the span it occupied."""
    for pattern in (_DAY_MONTH_YEAR, _MONTH_DAY_YEAR):
        for match in pattern.finditer(text or ""):
            month = _month_number(match.group("month"))
            if not month:
                continue
            try:
                found = datetime.date(
                    int(match.group("year")), month, int(match.group("day"))
                )
            except ValueError:
                continue
            return found, match.span()
    return None


def find_month(text: str) -> Optional[tuple[int, int]]:
    """``(year, month)`` from a title that names only the month."""
    for match in _MONTH_YEAR.finditer(text or ""):
        month = _month_number(match.group("month"))
        if month:
            return int(match.group("year")), month
    return None


def text_without_date(text: str) -> str:
    """A title with its date removed—what is left names the meeting.

    Takes the text before the date when there is any ("Council Meeting 10
    February 2026"), otherwise the text after it ("February 2, 2026 - Annual
    Meeting of Electors"). Whatever trails a leading name is a status, not
    part of it: "Special Electors' Meeting 3 February 2021 - Meeting
    Adjourned".
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    found = find_date(text)
    if not found:
        return text.strip(" -–—,:")
    _, (start, end) = found
    before = text[:start].strip(" -–—,:")
    return before or text[end:].strip(" -–—,:")


def tidy_meeting_name(name: str) -> str:
    """One spelling per meeting body.

    Titles are typed by hand per meeting, so a body appears as "Community and
    Resources Committee", "... Committee Meeting" and "... Committee Meeting
    Agenda" at Stirling, and as "Electors General Meeting" and "Electors'
    General Meeting" at Kwinana. Left alone, one body reads as several.
    """
    name = re.sub(r"\b(?:agenda|minutes)\b", "", name or "", flags=re.IGNORECASE)
    name = re.sub(r"\bCommittee Meeting\b", "Committee", name)
    name = re.sub(r"\bCEO'?s\b", "CEO", name)
    name = re.sub(r"\bElector'?s'?(?=\s)", "Electors'", name)
    name = re.sub(r",\s*and\b", " and", name)
    return re.sub(r"\s+", " ", name).strip(" -–—,")


def filename_of(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])


# A year on its own ("...-2026.pdf") or opening a compact date
# ("20240116-MO-JDAP-293-...").
_YEAR_IN_NAME = re.compile(r"(?<!\d)(20\d{2})(?:[01]\d[0-3]\d)?(?!\d)")
# A development application's number carries the year it was lodged, not the
# year of the meeting that decides it: "...JDAP-293-Agenda-(DA-696-2023).pdf"
# is the January 2024 agenda.
_APPLICATION_NUMBER = re.compile(r"\bDA[-_ ]?\d+[-_/ ]\d{4}\b", re.IGNORECASE)


def names_another_year(url: str, year: int) -> bool:
    """True when a document's filename is dated, and never with ``year``.

    The listings are hand-maintained, and now and then a meeting links the
    wrong meeting's file: Melville's 16 May 2023 minutes link points at
    ``Minutes-19-May-2026-OMC.pdf``, and one of Swan's 2023 panel meetings
    links ``...JDAP-211-Minutes-November-21,-2022.pdf``. A document that names
    a year, none of which is the meeting's, belongs to some other meeting.
    Filenames that name no year at all are given the benefit of the doubt.
    """
    name = _APPLICATION_NUMBER.sub("", filename_of(url))
    years = {int(y) for y in _YEAR_IN_NAME.findall(name)}
    return bool(years) and year not in years


def filename_says_minutes_only(url: str) -> bool:
    """True when a file offered as an agenda is named as minutes.

    Stirling's 4 October 2022 Planning and Development Committee lists its
    minutes file in the agenda slot too, and Swan's 1 December 2023 panel
    meeting labels a minutes PDF "Agenda". Storing those as the agenda would
    invent a document, so the label is checked against the filename.
    """
    name = filename_of(url).lower()
    return bool(re.search(r"minute|\bmins\b", name)) and "agenda" not in name


def filename_says_agenda_only(url: str) -> bool:
    """The converse: a file offered as minutes that is named as an agenda.

    Swan's 16 January 2024 panel meeting links the State's copy of the
    agenda under "Minutes".
    """
    name = filename_of(url).lower()
    return "agenda" in name and not re.search(r"minute|\bmins\b", name)


def quote_url(url: str) -> str:
    """Percent-encode a URL's path, leaving any existing escapes alone.

    Joondalup's file links carry raw spaces ("13 January 2026 - Special
    Council - Agenda.pdf"), which is not a valid URL however forgiving a
    browser is about it.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        parts._replace(path=urllib.parse.quote(parts.path, safe="/%"))
    )


class AlykaScraper(BaseScraper):
    """What every Alyka council shares: a listing page to read, a year bound."""

    # The page carrying the listing's hidden inputs. Set on the subclass.
    listing_url: str = ""

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    def _meeting(
        self,
        name: str,
        date: datetime.date,
        webpage_url: str,
        agenda_url: Optional[str],
        minutes_url: Optional[str],
        time: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[ScraperReturn]:
        """One meeting, after the checks every one of these listings needs.

        The documents are linked by hand, so before either is trusted: an
        agenda whose file is named as minutes is dropped rather than stored
        as an agenda, minutes named as an agenda likewise, and a file dated
        to some other year is dropped as belonging to some other meeting.
        What survives goes in the PDF fields only if it is a PDF—Kwinana's
        10 April 2024 agenda is a Word file—and otherwise in the HTML ones,
        as `DocsPublishedScraper` does. Returns None when nothing is left.
        """
        if agenda_url and filename_says_minutes_only(agenda_url):
            agenda_url = None
        if minutes_url and filename_says_agenda_only(minutes_url):
            minutes_url = None
        if agenda_url and names_another_year(agenda_url, date.year):
            agenda_url = None
        if minutes_url and names_another_year(minutes_url, date.year):
            minutes_url = None
        if not agenda_url and not minutes_url:
            return None

        def is_pdf(url):
            return bool(url) and filename_of(url).lower().endswith(".pdf")

        agenda_pdf = agenda_url if is_pdf(agenda_url) else None
        minutes_pdf = minutes_url if is_pdf(minutes_url) else None
        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=time,
            webpage_url=webpage_url,
            agenda_url=agenda_pdf,
            minutes_url=minutes_pdf,
            agenda_html_url=None if agenda_pdf else agenda_url,
            minutes_html_url=None if minutes_pdf else minutes_url,
            download_url=agenda_pdf or minutes_pdf,
            location=location,
        )

    def _log_result(self, results: list, searched: str) -> None:
        if results:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        else:
            self.logger.warning(
                f"{self.council_name} scraper found no meetings in {searched}"
            )

    def _listing_page(self) -> BeautifulSoup:
        return self._page(self.listing_url)

    def _each_year(self, years: Iterable[int], fetch) -> Iterable[tuple[int, object]]:
        """``(year, fetch(year))`` for each year, surviving a failed year.

        One year failing in a multi-year run should not cost the others, so it
        is logged and skipped. But production asks for a single year, and
        there a skipped year is the whole run: the scraper would return [] and
        land in council-alerts' ``okCouncils`` with 0 meetings, which is how a
        blocked host goes unnoticed. So when *every* year fails, the last
        error is raised instead.
        """
        years = list(years)
        failures = []
        for year in years:
            try:
                answer = fetch(year)
            except Exception as e:
                self.logger.warning(f"{self.council_name}: {year} failed: {e}")
                failures.append(e)
                continue
            yield year, answer
        if years and len(failures) == len(years):
            raise failures[-1]


# --------------------------------------------------------------------------
# Kendo ksearch
# --------------------------------------------------------------------------


class KsearchScraper(AlykaScraper):
    # Kendo pages by `page`/`pageSize`; `skip`/`take` are sent to match, as
    # the page itself does. Large enough that one request is normally the
    # whole answer.
    PAGE_SIZE = 1000
    # A guard, not an expectation: the largest council here needs one page.
    MAX_PAGES = 10

    def _ksearch_config(self, page: BeautifulSoup) -> tuple[str, str]:
        """The endpoint and the ``SearchParam`` header, as the page builds them.

        Mirrors ``aw_ksearch.js``: one entry per ``input[data-searchparam]``,
        its value split on commas, with ``or`` and ``operator`` passed through
        as the strings the attributes hold.
        """
        endpoint = page.find("input", id="searchapi")
        if not endpoint or not endpoint.get("value"):
            raise ValueError(f"No ksearch endpoint on {self.listing_url}")

        params = [
            {
                "key": element["id"],
                "values": (element.get("value") or "").split(","),
                "or": element.get("data-or"),
                "operator": element.get("data-operator"),
            }
            for element in page.find_all("input", attrs={"data-searchparam": True})
            if element.get("id")
        ]
        if not params:
            raise ValueError(f"No ksearch parameters on {self.listing_url}")

        return urllib.parse.urljoin(self.listing_url, endpoint["value"]), json.dumps(
            params
        )

    @staticmethod
    def multiselect_filter(key: str, values: Iterable) -> dict:
        """One ``SearchFilter`` entry, shaped as the page's multiselects send it."""
        return {
            "key": key,
            "values": [str(v) for v in values],
            "or": True,
            "operator": "",
            "datainput": "multiselect",
        }

    def _ksearch(
        self, endpoint: str, search_param: str, filters: list[dict]
    ) -> list[dict]:
        """Every record the endpoint returns for ``filters``.

        Stops on the first short page rather than paging until ``Total``.
        Stirling's ``Total`` counts records it then declines to return—2026
        reports 36 and yields 33 however it is paged—so a loop waiting to
        reach it would never end, or would end on a guard and look like a
        failure.
        """
        records: list[dict] = []
        for page in range(1, self.MAX_PAGES + 1):
            body = self.fetcher.fetch_with_requests(
                endpoint,
                "POST",
                json={
                    "take": self.PAGE_SIZE,
                    "skip": (page - 1) * self.PAGE_SIZE,
                    "page": page,
                    "pageSize": self.PAGE_SIZE,
                },
                headers={
                    "Content-Type": "application/json",
                    "SearchParam": search_param,
                    "SearchFilter": json.dumps(filters),
                },
            )
            data = json.loads(body).get("Data") or []
            records.extend(data)
            if len(data) < self.PAGE_SIZE:
                return records

        self.logger.warning(
            f"{self.council_name}: stopped paging after {self.MAX_PAGES} pages "
            f"of {self.PAGE_SIZE}; later records were not read"
        )
        return records


# --------------------------------------------------------------------------
# Page-type listing (htmlresult)
# --------------------------------------------------------------------------


class PageTypeListingScraper(AlykaScraper):
    # Rows per request. The server honours it, and a year of any of these
    # councils is well under it; `_warn_if_full` says so if that ever changes.
    PAGE_SIZE = 500

    def _warn_if_full(self, rows: int, what: str) -> None:
        """A full page means there may be more rows than were asked for."""
        if rows >= self.PAGE_SIZE:
            self.logger.warning(
                f"{self.council_name}: {what} returned a full page of {rows} "
                f"rows; raise PAGE_SIZE or page through, or meetings are missed"
            )

    def _listing_config(self, page: BeautifulSoup) -> dict:
        listing = page.find(id="pageTypeListing")
        if not listing or not listing.get("data-api"):
            raise ValueError(f"No page-type listing on {self.listing_url}")
        return {
            "endpoint": urllib.parse.urljoin(self.listing_url, listing["data-api"]),
            "search_index": listing.get("data-searchindex") or "",
            "filters": listing.find_all(attrs={"data-filter-item": True}),
        }

    @staticmethod
    def checkbox_values(config: dict, name: str) -> list[str]:
        """The options a checkbox filter offers, e.g. the years with records."""
        for element in config["filters"]:
            if element.get("data-filtername") == name:
                return [
                    box.get("value")
                    for box in element.find_all("input", type="checkbox")
                    if box.get("value")
                ]
        return []

    def _search(self, config: dict, chosen: dict[str, list[str]]) -> str:
        """The ``htmlResult`` fragment for the checkbox values in ``chosen``.

        ``PR`` mirrors ``_setFilterData`` in ``aw_pagetypelisting.js``: every
        filter item is sent, text inputs with their value and checkbox groups
        with whichever boxes are ticked—none, unless ``chosen`` names them.
        """
        parameters = []
        for element in config["filters"]:
            name = element.get("data-filtername")
            kind = element.get("data-filtertype")
            if kind == "text":
                field = element.find("input")
                value = (field.get("value") if field else "") or ""
                parameters.append({"key": name, "values": [{"value": value}]})
            elif kind == "checkbox":
                parameters.append(
                    {
                        "OR": True,
                        "key": name,
                        "operater": "like",
                        "values": [{"value": v} for v in chosen.get(name, [])],
                    }
                )

        body = self.fetcher.fetch_with_requests(
            config["endpoint"],
            "POST",
            json={
                "SI": config["search_index"],
                "OB": "",
                "Q": "",
                "PS": self.PAGE_SIZE,
                "FS": self.PAGE_SIZE,
                "PG": 1,
                "PR": parameters,
                "IncludeFirst": False,
            },
        )
        return json.loads(body).get("htmlResult") or ""
