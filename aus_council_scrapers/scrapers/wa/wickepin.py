import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wickepin.wa.gov.au"
_LANDING_URL = f"{_BASE_URL}/my-council/council/council-meetings.aspx"

# CouncilConnect CMS without its meetings module. The council menu links a
# hand-built page per year ("2025 Council Meetings"; the slugs are irregular:
# 2022-co.aspx, 2020-council-meetings-new.aspx), and each year page links a
# page per meeting, labelled with its date, under "Ordinary Meeting of
# Council" and "Special Meetings of Council" headings (2020-2022 put the
# type in the link text instead). The meeting page links the agenda,
# minutes, attachments and recording from /Profiles/wickepin/Assets/
# ClientData/, which robots.txt allows (only .../ModuleData/ is disallowed).
#
# A year costs its page plus one per meeting—about 14 requests—and only
# Council meetings are read. Committee meetings (Audit, Risk & Improvement,
# bush fire, emergency management) and electors' meetings have pages of
# their own and are not. Years before 2020 are a different shape (one
# page of agendas and one of minutes per year) and are out of range.
_YEAR_LINK = re.compile(r"^(20\d\d) Council Meetings$")
_WEEKDAY = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b,?", re.IGNORECASE
)
# A meeting link is labelled with its date ("Wednesday February 19, 2025",
# "21 February", "Ordinary Council Meeting 19th February 2020"). Checked
# before parsing, because dateutil's fuzzy mode fills a missing day from
# today rather than failing.
_DAY_AND_MONTH = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,}|\b[A-Za-z]{3,}\s+\d{1,2}\b"
)
# A full date in a file name ("Agenda_16_March_2022.pdf",
# "Agenda_November_18_2020_.pdf"). Names without a four-digit year
# ("Council_Agenda_February_26.pdf") are not checked.
_FILE_DATE = re.compile(
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+20\d\d\b|\b[A-Za-z]{3,9}\s+\d{1,2}\s+20\d\d\b"
)
_FILE_DATE_TOLERANCE_DAYS = 7
_AGENDA_LABEL = re.compile(r"^agenda$", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^(?:(?:un)?confirmed\s+)?minutes$", re.IGNORECASE)

# A new year's page goes into the menu once the council makes it, and the
# first meeting is in February (2020-2026: 15 February at the earliest,
# 14 March at the latest). So early in a year an absent or empty page is
# expected, and either is an error only once this much of the year has
# passed, the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


@register_scraper
class WickepinScraper(BaseScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP:
    # 12 requests, 22 s at the default FETCH_DELAY. Orders dispatch only;
    # see BaseScraper.expected_seconds.
    expected_seconds = 22

    def __init__(self):
        super().__init__("wickepin", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

    @staticmethod
    def _content(soup):
        # The page body; the rest of the page is menus that link every
        # year's page and a dozen policy PDFs.
        return soup.select_one("div.cp-placeholder")

    def _year(self, year: int, url: str) -> list[ScraperReturn]:
        content = self._content(self._soup(url))
        if content is None:
            raise RuntimeError(f"{self.council_name}: no content on {url}")

        results = []
        seen = set()
        dated_links = 0
        special = False
        for node in content.descendants:
            if isinstance(node, NavigableString):
                if node.find_parent("a") is None:
                    text = node.strip().lower()
                    if "special" in text:
                        special = True
                    elif "ordinary" in text:
                        special = False
                continue
            if node.name != "a" or not node.get("href"):
                continue
            label = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            href = urljoin(url, node["href"])
            if not label or href in seen:
                continue
            seen.add(href)

            if not _DAY_AND_MONTH.search(label):
                continue
            date_text = _WEEKDAY.sub(" ", label)
            date_text = re.sub(
                r"(?i)(ordinary|special)\s+council\s+meeting", " ", date_text
            )
            if not re.search(r"20\d\d", date_text):
                date_text = f"{date_text} {year}"
            try:
                date = parse_date(date_text, fuzzy=True, dayfirst=True).date()
            except (ValueError, OverflowError):
                continue
            dated_links += 1
            is_special = special or "special" in label.lower()
            name = (
                "Special Council Meeting" if is_special else "Ordinary Council Meeting"
            )

            if href.lower().endswith(".pdf"):
                # 31 March 2022's special meeting links its minutes straight
                # from the year page.
                agenda_url = None
                minutes_url = href if re.search(r"minute", href, re.I) else None
                agenda_url = (
                    href
                    if minutes_url is None and re.search(r"agenda", href, re.I)
                    else None
                )
            else:
                agenda_url, minutes_url = self._papers(href)
            agenda_url = self._same_meeting(agenda_url, date)
            minutes_url = self._same_meeting(minutes_url, date)
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=href if not href.lower().endswith(".pdf") else url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        if not dated_links and _owed_papers(year):
            # Each year page links a page per meeting, labelled by date, as
            # soon as the meeting is set, so none means the page changed.
            raise RuntimeError(f"{self.council_name}: no meeting links on {url}")
        return results

    def _same_meeting(self, url, date):
        """The URL, unless its file name dates it to another meeting.

        The 16 February 2022 page links Agenda_16_February_2021.pdf, which
        is the 17 February 2021 agenda (byte for byte the same file as
        Agenda_17_February_2021.pdf), and its minutes the same way.
        """
        if not url:
            return None
        match = _FILE_DATE.search(url.rsplit("/", 1)[-1].replace("_", " "))
        if match:
            try:
                stated = parse_date(match.group(), dayfirst=True).date()
            except (ValueError, OverflowError):
                return url
            if abs((stated - date).days) > _FILE_DATE_TOLERANCE_DAYS:
                self.logger.info(
                    f"{self.council_name}: {url} is dated {stated}, not {date}; left out"
                )
                return None
        return url

    @staticmethod
    def _one_meeting_per_file(results: list[ScraperReturn]) -> list[ScraperReturn]:
        """Keep a reused file name on the latest meeting that links it.

        Uploads go to one flat folder by file name, so a generic name is
        overwritten by the next upload with that name, and the URL then
        serves the newer meeting's paper. Council_Agenda.pdf is linked from
        15 February and 30 March 2023 and now holds the 30 March agenda;
        01_-_Council_Agenda.pdf (13 September and 18 October 2023) holds
        18 October's; Council_Minutes.pdf (30 March and 13 September 2023)
        holds 13 September's. Each was checked against the PDF's first page.
        """
        latest: dict[str, object] = {}
        for record in results:
            for url in (record.agenda_url, record.minutes_url):
                if url and (url not in latest or record.cleaned_date > latest[url]):
                    latest[url] = record.cleaned_date
        kept = []
        for record in results:
            if record.agenda_url and latest[record.agenda_url] != record.cleaned_date:
                record.agenda_url = None
            if record.minutes_url and latest[record.minutes_url] != record.cleaned_date:
                record.minutes_url = None
            if record.agenda_url or record.minutes_url:
                record.download_url = record.agenda_url or record.minutes_url
                kept.append(record)
        return kept

    def _papers(self, url: str):
        content = self._content(self._soup(url))
        agenda_url = minutes_url = None
        for link in content.find_all("a", href=True) if content else []:
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if not link["href"].lower().endswith(".pdf"):
                continue
            if agenda_url is None and _AGENDA_LABEL.match(label):
                agenda_url = urljoin(url, link["href"])
            elif minutes_url is None and _MINUTES_LABEL.match(label):
                minutes_url = urljoin(url, link["href"])
        return agenda_url, minutes_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        landing = self._soup(_LANDING_URL)
        year_pages = {}
        for link in landing.find_all("a", href=True):
            match = _YEAR_LINK.match(link.get_text(" ", strip=True))
            if match and not link["href"].startswith("javascript"):
                year_pages.setdefault(
                    int(match.group(1)), urljoin(_LANDING_URL, link["href"])
                )
        if not year_pages:
            raise RuntimeError(f"{self.council_name}: no year menu on {_LANDING_URL}")

        # A year that should have a page and does not is the menu changing,
        # not a quiet year; production asks for one year, so a warning
        # here would report an ok council with 0 meetings.
        missing = sorted(y for y in wanted if _owed_papers(y) and y not in year_pages)
        if missing:
            raise RuntimeError(
                f"{self.council_name}: no page in the menu on {_LANDING_URL} "
                f"for {missing}"
            )

        results = []
        for year in sorted(wanted & set(year_pages)):
            results.extend(
                r
                for r in self._year(year, year_pages[year])
                if r.cleaned_date.year == year
            )
        results = self._one_meeting_per_file(results)
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
