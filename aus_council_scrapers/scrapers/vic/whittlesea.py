import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.whittlesea.vic.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/About-us/Council/Council-meetings/Agendas-minutes-and-recordings"
)

# OpenCities, but not its meetings module: this is a hand-edited content page
# with every document linked in the HTML. It holds the current and previous
# year; earlier years move to a page of their own linked under "Previous
# meetings" (only 2024 exists—nothing before February 2024 is online). The
# year in each archive link's path says which year it holds, so production's
# single year costs one request.
_ARCHIVE_LINK = re.compile(r"/Agendas-minutes-and-recordings/(\d{4})-", re.IGNORECASE)

# Under h2 year sections ("2026 Council Meetings", "2025 Hearing of
# Submissions Committee") each meeting is a heading carrying its date and
# type: "20 October 2026 - Council Meeting". Some years add h3/h4 "Agenda" /
# "Minutes" subheadings, which carry no date and are not meetings.
#
# Every document comes twice, as a PDF and as an "accessible version" DOCX;
# only the PDF is taken.
_PDF = re.compile(r"\.pdf$", re.IGNORECASE)
_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
# A confidential meeting's minutes sit beside the public ones, and a
# "Public Resolution" is an extract, not the minutes.
_NOT_THE_MINUTES = re.compile(r"confidential", re.IGNORECASE)
# Two 2024 agendas are linked at /files/<uuid>/<name>.pdf—an editor's
# upload path rather than the published /files/assets/ or /files/content/
# store—and both answer 404 (checked October 2026). A link the council's own
# page cannot serve is not a document, so the meeting keeps only its minutes.
_UNPUBLISHED_UPLOAD = re.compile(r"/files/[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)
_SIZE_SUFFIX = re.compile(r"\((?:PDF|DOCX)[^)]*\)\s*$", re.IGNORECASE)
_WORDS = re.compile(r"[a-z]+", re.IGNORECASE)


@register_scraper
class WhittleseaScraper(BaseScraper):
    def __init__(self):
        super().__init__("whittlesea", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    def _heading(self, text: str):
        """(date, meeting type) when a heading names a meeting, else None."""
        match = self.date_regex.search(text)
        if not match:
            return None
        try:
            date = parse_date(match.group(), dayfirst=True).date()
        except (ValueError, OverflowError):
            return None
        name = text[match.end() :].strip(" -–—")
        # "6 May 2024 - Hearing of Submissions Committee Agenda" names the
        # document rather than the meeting.
        name = re.sub(r"\s+agenda$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"committee$", "Committee Meeting", name, flags=re.IGNORECASE)
        # The 2024 page heads ordinary meetings "Scheduled Council Meeting",
        # the later pages "Council Meeting". One type, so one name.
        name = re.sub(r"^scheduled\s+", "", name, flags=re.IGNORECASE)
        return date, name or "Council Meeting"

    def _is_bare_paper(self, label: str, name: str) -> bool:
        """True for a label that is just the meeting's name and date.

        Some agendas are not labelled as one: "Unscheduled Council Meeting -
        17 September 2024 (PDF, 29MB)", "Scheduled-Council-Meeting-18-June-
        2024.pdf". Once the size, date and meeting name are taken away,
        nothing is left—whereas the minutes, resolutions and attachments
        beside them always say what they are.
        """
        label = _SIZE_SUFFIX.sub("", label)
        label = re.sub(r"\.pdf\b", "", label, flags=re.IGNORECASE).replace("-", " ")
        label = self.date_regex.sub("", label)
        remaining = {w.lower() for w in _WORDS.findall(label)}
        if not remaining:
            # A link whose whole label is "(PDF, 1MB)".
            return False
        meeting_words = {w.lower() for w in _WORDS.findall(name)} | {"scheduled"}
        return remaining <= meeting_words

    def _parse(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find(id="main-content")
        if content is None:
            self.logger.warning(f"No content found on {page_url}")
            return []

        meetings: list[dict] = []
        current = None
        for element in content.find_all(["h2", "h3", "h4", "a"]):
            if element.name != "a":
                text = self._text(element)
                heading = self._heading(text)
                if heading:
                    current = {
                        "date": heading[0],
                        "name": heading[1],
                        "agenda": None,
                        "minutes": None,
                        "bare": None,
                    }
                    meetings.append(current)
                elif element.name == "h2":
                    # A new year section, or "Previous meetings": either way
                    # the last meeting's documents have ended.
                    current = None
                continue

            if current is None or not element.get("href"):
                continue
            href = urljoin(page_url, element["href"])
            if not _PDF.search(href) or _UNPUBLISHED_UPLOAD.search(href):
                continue
            label = self._text(element)
            if _MINUTES_LABEL.search(label):
                if current["minutes"] is None and not _NOT_THE_MINUTES.search(label):
                    current["minutes"] = href
            elif _AGENDA_LABEL.search(label):
                # Agendas split in parts list Part 1 first; it holds the
                # agenda proper, and later parts are attachments.
                if current["agenda"] is None:
                    current["agenda"] = href
            elif current["bare"] is None and self._is_bare_paper(label, current["name"]):
                current["bare"] = href

        results = []
        for m in meetings:
            agenda_url = m["agenda"] or m["bare"]
            if not agenda_url and not m["minutes"]:
                continue
            results.append(
                ScraperReturn(
                    name=m["name"],
                    date=m["date"].isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=m["minutes"],
                    download_url=agenda_url or m["minutes"],
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        listing_html = self.fetcher.fetch_with_requests(_LISTING_URL)
        pages = [(_LISTING_URL, listing_html)]

        archives: dict[int, str] = {}
        for link in BeautifulSoup(listing_html, "html.parser").find_all("a", href=True):
            match = _ARCHIVE_LINK.search(link["href"])
            if match:
                archives[int(match.group(1))] = urljoin(_LISTING_URL, link["href"])
        for year in sorted(wanted, reverse=True):
            url = archives.get(year)
            if not url:
                continue
            try:
                pages.append((url, self.fetcher.fetch_with_requests(url)))
            except Exception as e:
                self.logger.warning(f"Could not read Whittlesea's {year} page {url}: {e}")

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        for url, html in pages:
            for meeting in self._parse(html, url):
                key = (meeting.name, meeting.date)
                if key in seen or meeting.cleaned_date.year not in wanted:
                    continue
                seen.add(key)
                results.append(meeting)

        if not results:
            self.logger.warning("Whittlesea's agendas pages yielded no meetings with documents")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
