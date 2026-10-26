import math
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import DATE_REGEX, EARLIEST_YEAR
from aus_council_scrapers.meeting_documents import (
    AGENDA,
    MINUTES,
    Document,
    clean_name,
    group_documents,
    name_words,
)

_BASE_URL = "https://www.bayswater.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/city-and-council/council/council-meetings/agendas-and-minutes"
)

# The listing is an Alyka "MeetingDocuments" web part on Kentico. The page
# fills itself from this endpoint, which answers a plain GET with the same
# query string as the page (`year`, `page`) and returns only the results
# fragment—a twelfth the size of the page. Twelve items a page; the page
# size parameter is ignored however it is spelled.
_SEARCH_URL = f"{_BASE_URL}/aapi/meetingdocuments/search"
_ITEMS_PER_PAGE = 12

# The register changed shape at the start of 2024. From then on each item is
# one meeting ("Ordinary Council Meeting - 22 September 2026") with Agenda
# and Minutes sections holding files named "Agenda.pdf". Before that each
# item is one *document*, titled by hand ("Ordinary Council Meeting -
# Minutes - 8 December 2020", "Agenda - Audit and Risk Management Committee
# Meeting - 4 August 2020"), so agendas and minutes have to be paired up by
# title—see meeting_documents.py. Both shapes file their documents under
# the same section headings, which is what this reads.
#
# The headings are a filing choice, not a guarantee: audio files, addenda
# and "under separate cover" attachments are filed under Agenda or Minutes
# in the older years, and the occasional agenda sits under Minutes. So the
# document's own label decides what it is, and the heading only breaks a
# tie when the label says neither.
_SECTIONS = {"agenda": AGENDA, "minutes": MINUTES}
_KIND = re.compile(r"\b(agenda|minutes)\b", re.IGNORECASE)
_NOT_AGENDA_OR_MINUTES = re.compile(
    r"audio|recording|addend|separate\s+cover|\busc\b|supplementary|urgent"
    r"|replacement|late item|deputation|attach|confidential|summary|\bnotes\b"
    r"|new business|notice of motion|public question|\bitems?\s+\d",
    re.IGNORECASE,
)
_PART = re.compile(r"\bpart[\s_-]*0?(\d)", re.IGNORECASE)

# Agenda Briefing Forums are left out. A forum makes no decisions; what the
# register files as its "minutes" are summary notes, and in the older years
# its "agenda" is the next council meeting's agenda, which would put that
# agenda on a second record dated a week early.
_BRIEFING_FORUM = re.compile(r"agenda\s+brie", re.IGNORECASE)

# A handful of older titles give the day and month but no year ("Ordinary
# Council Meeting 8 December - Agenda"); the year is the one being listed.
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\b", re.IGNORECASE
)
_ANY_DATE = re.compile(rf"{DATE_REGEX.pattern}|{_DAY_MONTH.pattern}", re.IGNORECASE)
# Older documents live at a page alias under /<year>/<month>/, which is all
# there is to date the two or three titles that carry no date at all.
_URL_MONTH = re.compile(rf"/(\d{{4}})/({_MONTHS})/", re.IGNORECASE)


def _as_utf8(text: str) -> str:
    """Undo a UTF-8 body decoded as Latin-1.

    The search endpoint sends no charset, so requests falls back to
    ISO-8859-1 and an en dash in a title arrives as "â\\x80\\x93"—which
    then survives into meeting names.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


@register_scraper
class BayswaterScraper(BaseScraper):
    def __init__(self):
        super().__init__("bayswater", "WA", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _items(self, year: int) -> list[tuple[str, str, str, str]]:
        """Every (title, section heading, label, url) listed for `year`."""
        items = []
        page = 1
        while True:
            url = f"{_SEARCH_URL}?year={year}&page={page}"
            soup = BeautifulSoup(
                _as_utf8(self.fetcher.fetch_with_requests(url)), "html.parser"
            )
            count = soup.find("input", id="recordCountValue")
            total = int(count["value"]) if count and count.get("value") else 0

            titles = soup.select(".uk-accordion-title")
            for title in titles:
                content = title.find_next_sibling("div", class_="uk-accordion-content")
                if not content:
                    continue
                title_text = re.sub(r"\s+", " ", title.get_text(" ", strip=True))
                for heading in content.find_all("h3"):
                    listing = heading.find_next_sibling("ul")
                    for link in listing.select("a[href]") if listing else []:
                        name = link.select_one(".mnafile-name") or link
                        label = re.sub(r"\s+", " ", name.get_text(" ", strip=True))
                        items.append(
                            (
                                title_text,
                                heading.get_text(" ", strip=True),
                                label,
                                urljoin(_BASE_URL, link["href"]),
                            )
                        )

            if not titles or page >= math.ceil(total / _ITEMS_PER_PAGE):
                return items
            page += 1

    def _date(self, title: str, label: str, year: int):
        for text in (title, label):
            match = self.date_regex.search(text)
            if match:
                return parse_date(match.group(), dayfirst=True).date()
        match = _DAY_MONTH.search(title)
        if match:
            return parse_date(f"{match.group(1)} {match.group(2)} {year}").date()
        return None

    def _document(self, title, heading, label, url, year):
        """The item as a Document, or (kind, title, url) when it has no date."""
        if _BRIEFING_FORUM.search(title):
            return None
        section = _SECTIONS.get(heading.lower())
        if section is None or _NOT_AGENDA_OR_MINUTES.search(f"{title} {label}"):
            return None

        kind_match = _KIND.search(label)
        kind = kind_match.group(1).lower() if kind_match else section
        part = _PART.search(label)
        date = self._date(title, label, year)
        if date is None:
            return (kind, title, url)
        return Document(
            kind=kind,
            title=title,
            date=date,
            url=url,
            # Agendas split into parts: the first part carries the business.
            rank=int(part.group(1)) - 1 if part else 0,
        )

    def _place_undated(self, meetings, kind, title, url) -> None:
        """Attach a dateless document to the one meeting it can belong to."""
        where = _URL_MONTH.search(url)
        if not where:
            return
        month = parse_date(f"1 {where.group(2)} {where.group(1)}").date()
        words = name_words(clean_name(title, _ANY_DATE))
        candidates = [
            m
            for m in meetings
            if (m.date.year, m.date.month) == (month.year, month.month)
            and kind not in m.documents
            and words
            and (words <= m.words or m.words <= words)
        ]
        if len(candidates) == 1:
            candidates[0].documents[kind] = (0, url)
            candidates[0].names.setdefault(kind, clean_name(title, _ANY_DATE))
        else:
            self.logger.debug(f"Could not place undated document {title!r}")

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        results = []
        errors: list[Exception] = []
        for year in self._wanted_years():
            try:
                items = self._items(year)
            except Exception as e:
                self.logger.warning(f"Could not read the {year} listing: {e}")
                errors.append(e)
                continue

            seen = set()
            documents, undated = [], []
            for title, heading, label, url in items:
                # The index lists a few documents twice.
                if url in seen:
                    continue
                seen.add(url)
                document = self._document(title, heading, label, url, year)
                if isinstance(document, Document):
                    documents.append(document)
                elif document:
                    undated.append(document)

            meetings = group_documents(documents, _ANY_DATE)
            for kind, title, url in undated:
                self._place_undated(meetings, kind, title, url)

            for meeting in meetings:
                if meeting.date.year != year:
                    # A document dated outside the year it is listed under
                    # is a typo in its title, and would otherwise surface as
                    # a stray one-document meeting in another year.
                    continue
                results.append(
                    ScraperReturn(
                        name=meeting.name,
                        date=meeting.date.isoformat(),
                        time=meeting.stated_time,
                        webpage_url=f"{_LISTING_URL}?year={year}",
                        agenda_url=meeting.agenda_url,
                        minutes_url=meeting.minutes_url,
                        download_url=meeting.agenda_url or meeting.minutes_url,
                    )
                )

        # Production asks for one year, so one failed fetch can leave
        # nothing. An empty list does not raise, and main.py would count the
        # council as working with 0 meetings. Raise instead; a failure that
        # still leaves other years' meetings stays a warning.
        if not results and errors:
            raise errors[-1]
        if not results:
            self.logger.warning(f"{self.council_name}: no meetings found")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
