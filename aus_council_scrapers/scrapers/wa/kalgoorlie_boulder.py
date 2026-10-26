import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from dateutil.parser import parse as parse_date
from requests.utils import requote_uri

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper

# Since January 2026 the city has published its papers on an ordinary content
# page instead of the meetings module. The module's /past index stops at
# 2025, /past/2026 is a 404, and its upcoming page is empty; this page links
# every 2026 meeting's PDFs and says that "meetings held in 2025 and earlier"
# are in the module.
_PAPERS_PAGE = "/our-city/council/minutes-and-agendas.aspx"
_LAST_MODULE_YEAR = 2025

_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|October"
    r"|November|December"
)
# Each meeting on the papers page is introduced by a line of its own: an
# accordion heading for a past meeting ("Ordinary Council Meeting: 22
# September 2026"), a red span for an upcoming one ("Ordinary Council
# Meeting - 27 October 2026"). The year is sometimes left off ("Audit, Risk
# and Improvement Committee Meeting: 10 September").
_HEADING = re.compile(
    rf"^(?P<name>[A-Za-z][A-Za-z ,&'’]*?)\s*[:–—-]\s*"
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTHS})(?:\s+(?P<year>\d{{4}}))?$",
    re.IGNORECASE,
)
# The year folder every 2026 paper is filed in: .../Governance/2026_Meetings/...
# Used for a heading that gives only the day and month; the day itself is
# always the heading's.
_YEAR_FOLDER = re.compile(r"/(\d{4})_Meetings/", re.IGNORECASE)
# An upcoming meeting's second line: "To be held at 6pm at the Council
# Chambers, Kalgoorlie Town Hall. 316 Hannan Street, Kalgoorlie WA 6430."
_TO_BE_HELD = re.compile(
    r"^To be held at (?P<time>\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\.?)\s+at\s+"
    r"(?:the\s+)?(?P<location>.+?)\.?$",
    re.IGNORECASE,
)
# The papers page carries every body's meetings; only Council meetings are
# kept, to match what the module is read for (see the class docstring).
_COUNCIL_MEETING = re.compile(
    r"^(?P<kind>ordinary|special)\s+(?:council\s+meeting|meeting\s+of\s+council)$",
    re.IGNORECASE,
)


@register_scraper
class KalgoorlieBoulderScraper(TidyCouncilConnectScraper):
    """City of Kalgoorlie-Boulder—CouncilConnect to 2025, a content page since.

    Ordinary and Special Council meetings only. In the module (2018–2025)
    every meeting is a request, and the audit, finance, youth council and
    other committees would push a year past 30; on the papers page (2026 on)
    the whole year is one request, but the same two types are kept so the
    history reads the same throughout.

    The module filed the 16 June 2025 Ordinary meeting twice (pages 265 and
    274) with the same agenda and minutes; page 274's attachments are 27
    October's. `collapse_duplicates` keeps page 265.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The module's /past index starts at 2018.
    first_year = 2018
    # The module's upcoming page has listed nothing since the city moved
    # its papers; upcoming meetings are on the papers page.
    upcoming_path = None

    # Each read 20 Oct 2026.
    wrong_documents = {
        "https://www.ckb.wa.gov.au/council-meetings/ordinary-council-meeting/"
        "ordinary-council-meeting-14-february-2022/182/documents/"
        "co_14032022_agn_760.pdf": (
            "The agenda of the 14 March 2022 Ordinary meeting, filed under 14 "
            "February 2022 as well; that meeting keeps its minutes."
        ),
    }

    # The 11 October 2022 Special meeting's page (195) carries the 27
    # September 2022 Ordinary meeting's agenda and confirmed minutes, and
    # nothing of its own; the Ordinary meeting's page (194) has no papers.
    # Both papers' front pages say "Ordinary Council Meeting ... 7:00 PM ...
    # 27 September 2022" (read 20 Oct 2026), so page 195 is emitted as that
    # meeting, and the 11 October Special meeting, with no papers, is not.
    page_corrections = {
        "https://www.ckb.wa.gov.au/council-meetings/special-council-meeting/"
        "special-meeting-of-council-11-october-2022/195": {
            "name": "Ordinary Council Meeting",
            "date": "2022-09-27",
            "time": "7:00 PM",
            "why": "the 27 September 2022 Ordinary meeting's papers",
        },
    }

    # Headings are hand-typed and vary; the type names do not.
    name_by_type = True

    # One production year is the papers page alone: one request, 1 s
    # (measured 20 Oct 2026), so the 5 s default stands.

    def __init__(self):
        super().__init__("kalgoorlie_boulder", "WA", "https://www.ckb.wa.gov.au")

    # --- the papers page (2026 on) -----------------------------------------

    def _papers_page_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        url = urljoin(self.base_url, _PAPERS_PAGE)
        # Not caught: this page is the whole of every year from 2026, so
        # losing it must fail the council rather than report 0 meetings.
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        content = soup.find(id="r-speaker")
        if content is None:
            raise RuntimeError(f"{url}: no page content (id=r-speaker)")

        # Walk the page in document order: a heading line opens a meeting,
        # and every link up to the next heading is one of its papers.
        entries, current = [], None
        for node in content.descendants:
            if isinstance(node, NavigableString):
                text = re.sub(r"\s+", " ", str(node)).strip()
                heading = _HEADING.match(text)
                if heading:
                    current = {"heading": heading, "links": [], "held": None}
                    entries.append(current)
                elif current and _TO_BE_HELD.match(text):
                    current["held"] = _TO_BE_HELD.match(text)
            elif isinstance(node, Tag) and node.name == "a" and current:
                href = node.get("href")
                if href:
                    current["links"].append(
                        (
                            None,
                            node.get_text(" ", strip=True),
                            requote_uri(urljoin(url, href)),
                        )
                    )

        # No dated heading at all means the page has been rebuilt, not that
        # the city held no meetings; say so rather than return a short list.
        if not entries:
            raise RuntimeError(f"{url}: no dated meeting headings found")

        results, kept = [], set()
        for entry in entries:
            meeting = self._papers_page_meeting(entry, url)
            if meeting is None or parse_date(meeting.date).year not in wanted:
                continue
            key = (meeting.name, meeting.date)
            if key in kept:
                continue
            kept.add(key)
            results.append(meeting)
        return results

    def _papers_page_meeting(self, entry, url) -> Optional[ScraperReturn]:
        heading = entry["heading"]
        kind = _COUNCIL_MEETING.match(heading.group("name").strip())
        if not kind:
            return None
        name = f"{kind.group('kind').title()} Council Meeting"

        agenda_url, minutes_url = self._pick_documents(entry["links"])
        if not agenda_url and not minutes_url:
            return None

        year = heading.group("year")
        if year is None:
            folders = {
                found
                for _, _, link in entry["links"]
                for found in _YEAR_FOLDER.findall(unquote(urlparse(link).path))
            }
            if len(folders) != 1:
                self.logger.warning(
                    f"No year for {heading.group(0)!r} on {url}; skipped"
                )
                return None
            year = folders.pop()
        date = parse_date(
            f"{heading.group('day')} {heading.group('month')} {year}"
        ).date()

        time, location = None, None
        if entry["held"]:
            # "6pm", "10am", "5.30pm", "6 p.m.": the first dot between
            # digits is the hour's, any other is "p.m."'s.
            hour = re.sub(r"(\d)\.(\d)", r"\1:\2", entry["held"].group("time"))
            time = parse_date(hour.replace(".", "")).strftime("%I:%M %p").lstrip("0")
            location = entry["held"].group("location")

        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=time,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
            location=location,
        )

    # --- the scrape --------------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        if max(wanted) > _LAST_MODULE_YEAR:
            results.extend(self._papers_page_meetings(wanted))

        module_years = sorted(
            (y for y in wanted if self.first_year <= y <= _LAST_MODULE_YEAR),
            reverse=True,
        )
        self._labels = dict(self.meeting_types)
        seen: set[str] = set()
        results.extend(
            self.collapse_duplicates(self._past_meetings(module_years, seen))
        )

        if not results:
            raise RuntimeError(
                f"{self.council_name}: no meetings with documents for "
                f"{sorted(wanted)}; the papers page or the module may have changed"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
