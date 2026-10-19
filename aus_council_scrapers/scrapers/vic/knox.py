import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.knox.vic.gov.au"
_CURRENT_URL = (
    f"{_BASE_URL}/our-council/councillors-and-meetings/council-meetings"
    "/agenda-and-minutes/current-agendas-and-minutes"
)

# One page per year. The current year lives on the page above; every earlier
# year has an archive page, linked from it, ending agendas-and-minutes-YYYY.
# The links are read off the page rather than built, so a renamed archive is
# followed instead of guessed at. Production asks for one year, which is the
# current page alone: one request.
_ARCHIVE_LINK = re.compile(r"/agendas-and-minutes-(\d{4})/?$")

# Each page lists meetings under h2 sections—"Council meetings", and on
# older pages "Strategic Planning Committee (SPC) meetings" and "Special
# meetings of Council" as well; these are the "two separate lists" the
# council list warns about. Under each section a heading per meeting carries
# its date: an accordion h3 since 2021, a bare h3 in 2020, and once in 2020 an
# h2 holding the date itself. Walking headings and links in document order
# and pinning each link to the last dated heading handles all three.
_STOP_SECTIONS = re.compile(
    r"request a printed agenda|watch previous|hard copies|need help|related links",
    re.IGNORECASE,
)

# Every document link is labelled by what it is first: "Agenda - Council
# Meeting - 27 January 2026", "Minutes - Mid Month Meeting - ...". Matching the
# start of the label keeps out "Supplementary Agenda", "Agenda Summary",
# notices of motion, attachments, and the "Minutes Update" that follows a
# meeting's real minutes. Knox's minutes are usually a combined
# "Minutes and Agenda" file; it is still the minutes.
_AGENDA_LABEL = re.compile(r"^agenda\b(?!\s*summary)", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^minutes\b(?!\s*update)", re.IGNORECASE)

# Some headings and link labels leave the year off ("Monday 16 August (ad hoc
# meeting)", "Agenda - Mid Month Meeting - 14 September"), so a day and month
# are enough; the year then comes from the page.
_DAY_MONTH = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_CANCELLED = re.compile(r"\bcancelled\b", re.IGNORECASE)
_START_TIME = re.compile(r"start time:\s*([\d.:]+\s*[ap]\.?m\.?)", re.IGNORECASE)


@register_scraper
class KnoxScraper(BaseScraper):
    def __init__(self):
        super().__init__("knox", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _text(element) -> str:
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    @staticmethod
    def _page_year(soup: BeautifulSoup, fallback: int) -> int:
        heading = soup.find("h1")
        match = re.search(r"\b(20\d{2})\b", heading.get_text() if heading else "")
        return int(match.group(1)) if match else fallback

    def _date(self, text: str, year: int):
        match = _DAY_MONTH.search(text)
        if not match:
            return None
        stamp = match.group(0) if match.group(1) else f"{match.group(0)} {year}"
        try:
            return parse_date(stamp, dayfirst=True).date()
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _meeting_name(context: str) -> str:
        """The meeting type, from everything the page says about the meeting.

        Knox describes one meeting several ways at once—the section, the
        heading, an accordion caption and the link labels—and they do not
        always agree: 10 November 2025 is "Mid-month" in its heading and
        "Council meeting" in its caption. Any mention wins, so the more
        specific type is kept.
        """
        if re.search(r"strategic planning|\bSPC\b", context, re.IGNORECASE):
            return "Strategic Planning Committee Meeting"
        if re.search(r"mid[\s-]?month", context, re.IGNORECASE):
            return "Mid-Month Council Meeting"
        if re.search(r"\bspecial\b", context, re.IGNORECASE):
            return "Special Council Meeting"
        if re.search(r"ad[\s-]?hoc", context, re.IGNORECASE):
            return "Ad Hoc Council Meeting"
        return "Council Meeting"

    def _parse(self, html: str, page_url: str, page_year: int) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", class_="field--name-field-landing-page-content")
        if content is None:
            self.logger.warning(f"No meeting content found on {page_url}")
            return []
        page_year = self._page_year(soup, page_year)

        meetings: list[dict] = []
        section = ""
        current = None
        for element in content.find_all(["h2", "h3", "a"]):
            if element.name == "a":
                if current is None or not element.get("href"):
                    continue
                href = urljoin(page_url, element["href"])
                if not href.lower().endswith(".pdf"):
                    continue
                label = self._text(element)
                if current["agenda"] is None and _AGENDA_LABEL.search(label):
                    current["agenda"] = href
                    current["labels"].append(label)
                elif current["minutes"] is None and _MINUTES_LABEL.search(label):
                    current["minutes"] = href
                    current["labels"].append(label)
                continue

            text = self._text(element)
            if element.name == "h2":
                if _STOP_SECTIONS.search(text):
                    break
                section = text
            date = self._date(text, page_year)
            if date is None:
                # A section heading, or a non-meeting entry such as "October
                # 2020 — no meeting due to the election period".
                current = None
                continue

            # The accordion body that follows an h3 opens with a caption
            # naming the meeting type ("Mid-month Council meeting") and then
            # its start time. Only the caption feeds the name: the rest of the
            # body carries notice-of-motion titles, which can say anything.
            body = element.find_next_sibling("div", class_="accordion__options")
            caption = body.find("p") if body else None
            body_text = self._text(body) if body else ""
            current = {
                "date": date,
                "context": " ".join([section, text, self._text(caption) if caption else ""]),
                "time": _START_TIME.search(body_text),
                # Mostly flagged in the heading ("Meeting Cancelled"), but 15
                # March 2022 says so only in a note under it—with its agenda
                # still attached.
                "cancelled": bool(_CANCELLED.search(text))
                or any(
                    _CANCELLED.search(self._text(note))
                    for note in (body.find_all("p") if body else [])
                    if not note.find("a")
                ),
                "agenda": None,
                "minutes": None,
                "labels": [],
            }
            meetings.append(current)

        results = []
        for m in meetings:
            if m["cancelled"] or not (m["agenda"] or m["minutes"]):
                # Scheduled but not yet papered, or a meeting that never ran.
                continue
            context = " ".join([m["context"], *m["labels"]])
            results.append(
                ScraperReturn(
                    name=self._meeting_name(context),
                    date=m["date"].isoformat(),
                    time=m["time"].group(1) if m["time"] else None,
                    webpage_url=page_url,
                    agenda_url=m["agenda"],
                    minutes_url=m["minutes"],
                    download_url=m["agenda"] or m["minutes"],
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        current_html = self.fetcher.fetch_with_requests(_CURRENT_URL)
        pages = [(_CURRENT_URL, current_html, this_year)]

        archives: dict[int, str] = {}
        for link in BeautifulSoup(current_html, "html.parser").find_all("a", href=True):
            match = _ARCHIVE_LINK.search(link["href"])
            if match:
                archives[int(match.group(1))] = urljoin(_CURRENT_URL, link["href"])
        if not archives:
            self.logger.warning(
                "Knox's current agendas page links no yearly archives; only the "
                "current year can be read"
            )

        for year in sorted(wanted, reverse=True):
            url = archives.get(year)
            if not url:
                continue
            try:
                pages.append((url, self.fetcher.fetch_with_requests(url), year))
            except Exception as e:
                self.logger.warning(f"Could not read Knox's {year} archive {url}: {e}")

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        for url, html, year in pages:
            for meeting in self._parse(html, url, year):
                # Around New Year a year can sit on both the current page and
                # its new archive page.
                key = (meeting.name, meeting.date, meeting.agenda_url)
                if key in seen or meeting.cleaned_date.year not in wanted:
                    continue
                seen.add(key)
                results.append(meeting)

        if not results:
            self.logger.warning("Knox's agendas pages yielded no meetings with documents")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
