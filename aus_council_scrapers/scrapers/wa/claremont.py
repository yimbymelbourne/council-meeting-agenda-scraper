import datetime
import json
import re
from collections import Counter
from typing import Optional
from urllib.parse import urljoin

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.claremont.wa.gov.au"

# The listing page is a shell; its `data-equ-listingfilter` attribute names
# this endpoint and the parent node holding every meeting. The endpoint takes
# any page size (and only GET—POST answers 405), so the whole archive, 686
# entries back to 2015, is one ~500 KB request. It ignores a `year` parameter,
# so years are filtered here rather than on the server.
_SEARCH_URL = (
    f"{_BASE_URL}/umbraco/api/search/query"
    "?parentId=1592&pagesize=2000&page=1&template=minues-and-agenda"
)

# Two shapes of entry, because the site changed how it files documents in
# 2025:
#
# - Newer entries are one per meeting, with the documents sorted into
#   `AgendaAttachments` and `MinutesAttachments` (plus `SupplementaryAgendas`
#   and loose `Attachments`, neither of which is the meeting's agenda).
# - Older entries—650 of them—are one per *document*, each holding a single
#   file in `Attachments`, so a meeting's agenda and its minutes are two
#   entries with the same title and date. Which is which has to be read off
#   the document; see `_kind`.
_MINUTES = re.compile(r"\bminutes?\b|\bmin\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda|\bagn\b", re.IGNORECASE)
# A supplementary agenda is a second document for a meeting that already has
# an agenda, and an attachment bundle is not an agenda at all. "Minutes ...
# Public With Attachments" is still the minutes, so only an attachment that
# is named as one is excluded.
_NOT_THE_MEETINGS = re.compile(
    r"supplementary|separate cover"
    r"|^\s*(?:public |amended )?attachments?\b|attachments? to\b|\bitem\s+\d",
    re.IGNORECASE,
)

# Entry titles are the meeting type, typed by hand: "Commitee", a trailing
# " Meeting" on some committees but not others, a parenthetical remark
# (including, once, a paragraph about a failed recording), and a couple of
# titles that are really file names. Normalising them is what lets an old
# agenda entry and its minutes entry land on the same record.
_PARENTHETICAL = re.compile(r"\s*\(.*?\)\s*")
_ALIASES = {
    "annual general electors meeting": "Annual General Meeting of Electors",
    "annual general minutes of electors": "Annual General Meeting of Electors",
    "audit and risk committee": "Audit and Risk Management Committee",
    "audit, risk and management committee": "Audit and Risk Management Committee",
}
_ABBREVIATIONS = {
    "ocm": "Ordinary Council Meeting",
    "lcac": "Lake Claremont Advisory Committee",
}

_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
# "OCM Agenda 3 February 2015", and the slug form "ocm-agenda-17-apr-2018" or
# "lcac-minutes-10-nov-22" once hyphens are read as spaces.
_WRITTEN_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"\s+(\d{4}|\d{2})\b",
    re.IGNORECASE,
)
# The records system's own file code: "FAC 20230222 MIN 2310 AT".
_COMPACT_DATE = re.compile(r"\b(20\d{2})(\d{2})(\d{2})\b")


def _spaced(text: str) -> str:
    return re.sub(r"[-_]+", " ", text)


@register_scraper
class ClaremontScraper(BaseScraper):
    def __init__(self):
        super().__init__("claremont", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _meeting_name(title: str) -> Optional[str]:
        """The meeting type, or None for an entry that is not a meeting's own.

        Entries titled "... (Supplementary Agenda)", "(Item 13.1.1)" or
        "Supplementary Ordinary Council Meeting" hold only a supplementary
        agenda or a report's attachments.
        """
        title = re.sub(r"\s+", " ", title).strip()
        if re.search(r"supplementary|\(item\b", title, re.IGNORECASE):
            return None

        name = _PARENTHETICAL.sub(" ", title).strip()
        name = re.sub(r"\bcommitee\b", "Committee", name, flags=re.IGNORECASE)
        name = re.sub(r"\b(Committee) Meeting$", r"\1", name)

        first_word = name.split(" ", 1)[0].lower()
        if first_word in _ABBREVIATIONS:
            return _ABBREVIATIONS[first_word]
        return _ALIASES.get(name.lower(), name)

    @staticmethod
    def _kind(*texts: str) -> Optional[str]:
        """Agenda, minutes or neither, from the first text that says.

        The caller passes the file's own name first. The file title is typed
        separately and is sometimes wrong where the file name is right: both
        of Ordinary Council's 7 July 2020 entries are titled "OCM Agenda 7
        July 2020 Public" and both link ocm-minutes-7-july-2020-confirmed-
        public.pdf, which is the minutes. Read by title, the minutes would be
        stored as the agenda.
        """
        for text in texts:
            if not text:
                continue
            if _NOT_THE_MEETINGS.search(text):
                return None
            if _MINUTES.search(text):
                return "minutes"
            if _AGENDA.search(text):
                return "agenda"
        return None

    @staticmethod
    def _written_date(text: str) -> Optional[str]:
        for match in _COMPACT_DATE.finditer(text):
            try:
                return datetime.date(*map(int, match.groups())).isoformat()
            except ValueError:
                continue
        match = _WRITTEN_DATE.search(text)
        if not match:
            return None
        day, month, year = match.groups()
        year = int(year) + 2000 if len(year) == 2 else int(year)
        try:
            return datetime.date(
                year, _MONTHS.index(month[:3].lower()) + 1, int(day)
            ).isoformat()
        except ValueError:
            return None

    def _meeting_date(self, entry_date: str, slug: str, file_title: str) -> str:
        """Which meeting a document belongs to.

        Three places state a date, and each is wrong somewhere. The entry
        date is wrong for "FAC Agenda 15 July 2020", filed under 2019-07-15.
        The slug is wrong for fac-agenda-25-august-2022, whose file code and
        entry both say 24 August. The file title is wrong for "Museum
        Advisory Committee Agenda 7 March 2022", whose PDF is the 7 June 2022
        agenda, as the entry and slug say. So the majority wins, and a tie or
        a date stated only once falls back to the entry date. Checked against
        the front pages of thirteen disputed PDFs from 2017 on, that rule
        picks the right meeting every time; each source on its own gets at
        least two of the thirteen wrong.
        """
        votes = Counter(
            d
            for d in (
                entry_date,
                self._written_date(_spaced(slug)),
                self._written_date(file_title),
            )
            if d
        )
        if not votes:
            return entry_date
        best, count = votes.most_common(1)[0]
        return best if count > 1 or not entry_date else entry_date

    @staticmethod
    def _pdf_url(attachment: dict) -> Optional[str]:
        url = attachment.get("FileUrlString") or attachment.get("FileUrl")
        if not url:
            return None
        url = urljoin(_BASE_URL, url)
        return url if url.lower().endswith(".pdf") else None

    def _documents(self, entry: dict, page_url: str) -> list[tuple]:
        """(kind, url, meeting date) for each of an entry's own documents."""
        # `Date` is midnight with a "Z", but it is the meeting's local date:
        # it agrees with `DateString` ("23 Oct 2026") on all 686 entries, so
        # it is read as a date and not converted.
        entry_date = (entry.get("Date") or "")[:10]

        if entry.get("AgendaAttachments") or entry.get("MinutesAttachments"):
            docs = []
            for kind, field in (
                ("agenda", "AgendaAttachments"),
                ("minutes", "MinutesAttachments"),
            ):
                urls = [self._pdf_url(a) for a in entry.get(field) or []]
                urls = [u for u in urls if u]
                if urls:
                    docs.append((kind, urls[0], entry_date))
            return docs

        docs = []
        slug = page_url.rstrip("/").rsplit("/", 1)[-1]
        for attachment in entry.get("Attachments") or []:
            url = self._pdf_url(attachment)
            if not url:
                continue
            file_title = attachment.get("FileTitle") or ""
            file_name = _spaced(url.rsplit("/", 1)[-1][: -len(".pdf")])
            kind = self._kind(file_name, file_title, _spaced(slug))
            if not kind:
                continue
            docs.append((kind, url, self._meeting_date(entry_date, slug, file_title)))
        return docs

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        body = json.loads(self.fetcher.fetch_with_requests(_SEARCH_URL))
        entries = body.get("Results") or []
        # Raise rather than return []: an empty list counts as a working
        # council in the nightly run, and this one request is the whole
        # archive, so it is never legitimately empty.
        if body.get("ErrorMessage") or not entries:
            raise RuntimeError(
                f"{self.council_name}: {_SEARCH_URL} returned {len(entries)} "
                f"entries (error: {body.get('ErrorMessage')!r})"
            )

        wanted = self._wanted_years()
        meetings: dict[tuple, dict] = {}

        for entry in entries:
            name = self._meeting_name(entry.get("Title") or "")
            if not name:
                continue

            page_url = urljoin(_BASE_URL, entry.get("URL") or "")
            for kind, url, date in self._documents(entry, page_url):
                if not date or int(date[:4]) not in wanted:
                    continue
                meeting = meetings.setdefault(
                    (name, date), {"page": page_url, "agenda": None, "minutes": None}
                )
                # A handful of documents were uploaded twice, as two entries
                # (Foreshore Advisory, 24 November 2021, has both its agenda
                # and its minutes twice). The first listed is kept.
                if meeting[kind] is None:
                    meeting[kind] = url

        results = []
        for (name, date), meeting in meetings.items():
            agenda_url, minutes_url = meeting["agenda"], meeting["minutes"]
            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=meeting["page"],
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
