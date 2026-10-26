import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://irwin.wa.gov.au"
# The current year's meetings page. Despite its slug it is the 2026 page, and
# it links every year's page by a bare year ("2025", "2024", ...), whose slugs
# are just as irregular (/council-meetings-2/ is 2024), so the year pages are
# read off it rather than built.
_START_URL = _BASE_URL + "/council-meetings-2025/"

# Each year page is a table: Date | Time | Meeting | Documents. From 2025 the
# Documents cell is a "Click Here" link to a post per meeting that holds the
# papers; 2022-2024 link the papers in the cell itself. A production year is
# the year page plus one post per Council meeting, about 15 requests.
#
# Agenda forums (councillor briefings) and the annual electors' meeting share
# the table and are skipped: they are not Council meetings, and skipping
# forums halves the per-meeting posts fetched.
_SKIPPED_MEETINGS = re.compile(r"forum|elector", re.IGNORECASE)

# Labels and file names disagree: the 26 April 2023 "Ordinary-Council-
# Meeting-Agenda-26-April-2023_1" link is the minutes, and the 27 June 2023
# "attachment booklet" link is the minutes too. A descriptive file name is
# trusted over the label. Where the file name says nothing, the label is all
# there is: 2022's files are named by GUID, and from late 2025 confirmed
# minutes are scanner output ("SKM_C55825100110060.pdf") linked as "Confirmed
# Minutes".
_GUID_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$",
    re.IGNORECASE,
)
_NOT_A_PAPER = re.compile(
    r"attach|booklet|forum|notes|late|annual[\s_-]*report|\bagm\b|agm-",
    re.IGNORECASE,
)
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_DATE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.IGNORECASE,
)


def _parse(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text.replace("​", " "))
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
    except ValueError:
        return None


def _classify(label: str, url: str) -> Optional[str]:
    path = urlsplit(url).path
    # 2022's March agenda is linked as a bare "858b8ac0-...pdf" (and once as
    # "http://858b8ac0-...pdf"), which resolves nowhere.
    if "/wp-content/uploads/" not in path or not path.lower().endswith(".pdf"):
        return None
    name = unquote(path.rsplit("/", 1)[-1])
    texts = [label] if _GUID_NAME.match(name) else [name, label]
    for text in texts:
        if _NOT_A_PAPER.search(text):
            return None
        if re.search(r"minute", text, re.IGNORECASE):
            return "minutes"
        if re.search(r"agenda", text, re.IGNORECASE):
            return "agenda"
    return None


def _special(text: str) -> bool:
    return bool(re.search(r"special|\bscm\b|scm-|-scm", text, re.IGNORECASE))


def _is_post(url: str) -> bool:
    """A link to a meeting's own post, rather than to a file."""
    parts = urlsplit(url)
    return (
        parts.netloc.endswith("irwin.wa.gov.au")
        and "/wp-content/" not in parts.path
        and not re.search(r"\.[a-z0-9]{2,4}$", parts.path, re.IGNORECASE)
    )


def _confirmed(label: str, url: str) -> bool:
    text = f"{label} {url}".lower()
    return "confirmed" in text and "unconfirmed" not in text


@register_scraper
class IrwinScraper(BaseScraper):
    expected_seconds = 27.0

    def __init__(self):
        super().__init__("irwin", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _papers(links) -> tuple[Optional[str], Optional[str], str, str]:
        """The row's agenda and minutes, and the text each was chosen by."""
        agenda_url = minutes_url = None
        agenda_text = minutes_text = ""
        minutes_confirmed = False
        for link in links:
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            url = urljoin(_BASE_URL, link["href"].strip())
            kind = _classify(label, url)
            if kind is None:
                continue
            text = f"{label} {unquote(url.rsplit('/', 1)[-1])}"
            if kind == "agenda":
                if agenda_url is None:
                    agenda_url, agenda_text = url, text
            elif minutes_url is None or (
                _confirmed(label, url) and not minutes_confirmed
            ):
                # Confirmed minutes replace the unconfirmed ones once adopted;
                # 2022 rows list both.
                minutes_url, minutes_text = url, text
                minutes_confirmed = _confirmed(label, url)
        return agenda_url, minutes_url, agenda_text, minutes_text

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        start_html = self.fetcher.fetch_with_requests(_START_URL)
        start = BeautifulSoup(start_html, "html.parser")
        year_pages: dict[int, str] = {}
        for link in start.find_all("a", href=True):
            text = link.get_text(" ", strip=True)
            if re.fullmatch(r"20\d{2}", text):
                year_pages.setdefault(
                    int(text), urljoin(_START_URL, link["href"].strip())
                )
        if not year_pages:
            raise ValueError(f"{self.council_name}: no year links on {_START_URL}")

        # The year pages start at 2022. A year from then to now with no page
        # means the start page has stopped being the current one (its slug is
        # hard-coded) or the council has moved things; either way nothing was
        # read for that year, so fail rather than report an empty year.
        missing = [
            y
            for y in wanted
            if y <= clock.current_year() and y >= 2022 and y not in year_pages
        ]
        if missing:
            raise ValueError(
                f"{self.council_name}: no page linked for {sorted(missing)} "
                f"on {_START_URL}"
            )

        results: list[ScraperReturn] = []
        for year in sorted(wanted & set(year_pages), reverse=True):
            page = year_pages[year]
            html = (
                start_html
                if page.rstrip("/") == _START_URL.rstrip("/")
                else self.fetcher.fetch_with_requests(page)
            )
            rows = BeautifulSoup(html, "html.parser").find_all("tr")
            found = 0
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                date = _parse(cells[0].get_text(" ", strip=True))
                meeting = re.sub(r"\s+", " ", cells[2].get_text(" ", strip=True))
                if (
                    date is None
                    or date.year != year
                    or _SKIPPED_MEETINGS.search(meeting)
                ):
                    continue
                links = cells[3].find_all("a", href=True)
                # The 2022-2023 pages show "06:00" for every meeting, a
                # placeholder; from 2024 the times are real.
                time = cells[1].get_text(" ", strip=True) or None
                if time == "06:00":
                    time = None
                webpage = page
                posts = [
                    url
                    for url in (urljoin(_BASE_URL, a["href"].strip()) for a in links)
                    if _is_post(url)
                ]
                if posts:
                    # The post's slug is sometimes another meeting's (the 27
                    # May 2025 row links ".../22-april-2025-ordinary-council-
                    # meeting/"), but its contents are the row's meeting, so
                    # the date comes from the row.
                    webpage = posts[0]
                    post = BeautifulSoup(
                        self.fetcher.fetch_with_requests(webpage), "html.parser"
                    )
                    links = post.find_all("a", href=True)
                agenda_url, minutes_url, agenda_text, minutes_text = self._papers(links)
                # The Meeting cell names the type from 2024 on; earlier rows say
                # "Agenda" or "Council Meeting", and the papers' names tell
                # instead. A special meeting's minutes always say so, so on
                # those rows an agenda marked special beside minutes that are
                # not belongs to another meeting: the "28 November 2023 |
                # Council Meeting" row links the 6 November special meeting's
                # "1-Agenda-SCM-Nov-2023-Copy.pdf" beside the 28 November
                # ordinary minutes. That agenda is dropped, and the row is the
                # ordinary meeting the minutes record (Irwin holds no other
                # kind; forums and electors' meetings are skipped above).
                names_type = re.search(r"special|ordinary", meeting, re.IGNORECASE)
                evidence = f"{agenda_text} {minutes_text}"
                if (
                    not names_type
                    and agenda_url
                    and minutes_url
                    and _special(agenda_text)
                    and not _special(minutes_text)
                ):
                    self.logger.info(
                        f"{self.council_name}: {date} special-meeting agenda "
                        f"{agenda_url} sits beside non-special minutes—dropped"
                    )
                    agenda_url = None
                    evidence = "ordinary"
                if not agenda_url and not minutes_url:
                    continue
                found += 1
                if names_type:
                    evidence = meeting
                if _special(evidence):
                    name = "Special Council Meeting"
                elif re.search(r"ordinary|\bocm\b|ocm-", evidence, re.IGNORECASE):
                    name = "Ordinary Council Meeting"
                else:
                    name = "Council Meeting"
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=time,
                        webpage_url=webpage,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )
            if not found and year <= clock.current_year():
                self.logger.warning(
                    f"{self.council_name}: no meetings with papers on {page}"
                )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
