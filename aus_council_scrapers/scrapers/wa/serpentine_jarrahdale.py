import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper

SITE = "https://www.sjshire.wa.gov.au"

# CouncilConnect paths for one meeting type's past meetings in one year.
# The archive is read per type rather than through the all-types year
# listing, which is mostly audit and CEO committees and runs to three pages.
ARCHIVE_TYPES = {
    "ordinary-council-meeting": "Ordinary Council Meeting",
    "special-council-meeting": "Special Council Meeting",
}


@register_scraper
class SerpentineJarrahdaleScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP in a full
    # 135-council run at 10 workers: 20 s, most of it queued behind the
    # other tenants on api.resolve.red (9 s alone). Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 20

    # Serpentine-Jarrahdale's council page links its Resolve portal (the
    # older DevExpress one, at /web/) for meetings from 21 July 2025, and a
    # CouncilConnect library at sjshire.wa.gov.au/council-meetings/past/<year>
    # for 2001 to June 2025, which `other_meetings` reads. Production asks
    # for a year that is all Resolve, so the library costs it nothing.
    #
    # The /web/ grid's document links carry a token, but the tokenless
    # DocPreview URL the base class emits serves the same PDFs.
    tenant = "sjshire"
    resolve_from = datetime.date(2025, 7, 21)

    # Ordinary and Special Council. The tenant files special meetings under
    # three types: "Special Council", "Special Council Meeting - CEO
    # recruitment" and "Swearing In Ceremony and Special Council Meeting".
    # Left out are audit, the CEO employment committee and the electors'
    # general meeting; each kept meeting costs a request to learn which
    # documents it has.
    meeting_types = re.compile(r"^(Ordinary Council|.*\bSpecial Council\b)")
    meeting_type_names = {
        "Ordinary Council": "Ordinary Council Meeting",
        "Special Council": "Special Council Meeting",
        "Special Council Meeting - CEO recruitment": "Special Council Meeting",
        "Swearing In Ceremony and Special Council Meeting": ("Special Council Meeting"),
    }

    def __init__(self):
        super().__init__("serpentine_jarrahdale", "WA")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # A type-year is one listing page, or two for the eleven or so
        # ordinary meetings a year, then one request per meeting for its
        # documents, which are only on the meeting's own page.
        results = []
        for year in self.before_resolve(wanted):
            if year < EARLIEST_YEAR:
                continue
            listed, unreadable = 0, []
            for slug, name in ARCHIVE_TYPES.items():
                for summary in self._listing(slug, year):
                    if summary["date"] >= self.resolve_from:
                        continue
                    listed += 1
                    try:
                        record = self._meeting(summary, name)
                    except Exception as e:
                        # One meeting lost is a warning.
                        self.logger.warning(
                            f"{self.council_name}: could not read {summary['url']}: {e}"
                        )
                        unreadable.append(summary["url"])
                        continue
                    if record:
                        results.append(record)
            if listed and len(unreadable) == listed:
                # Every meeting page failed, so the year would come back
                # empty while the council reported success.
                raise RuntimeError(
                    f"{self.council_name}: none of the {listed} meeting pages "
                    f"listed for {year} could be read"
                )
        return results

    def _listing(self, slug: str, year: int) -> list[dict]:
        """Every meeting of one type in one year, from the paged listing.

        Ten meetings a page. Later pages are not links but `__doPostBack`
        calls on the `dpMeetings` pager, so each is the page's own form
        posted back with that pager link as the event target."""
        url = f"{SITE}/council-meetings/{slug}/past/{year}"
        html = self.fetcher.fetch_with_requests(url)
        summaries = _summaries(html)
        page = 2
        while True:
            target = _pager_target(html, page)
            if not target:
                return summaries
            form = BeautifulSoup(html, "html.parser")
            data = {
                field["name"]: field.get("value", "")
                for field in form.find_all("input", type="hidden")
                if field.get("name")
            }
            data["__EVENTTARGET"] = target
            data["__EVENTARGUMENT"] = ""
            html = self.fetcher.fetch_with_requests(url, method="POST", data=data)
            summaries += _summaries(html)
            page += 1

    def _meeting(self, summary: dict, name: str) -> Optional[ScraperReturn]:
        url = summary["url"]
        html = self.fetcher.fetch_with_requests(url)
        agenda_url, minutes_url = _papers(html, url)
        if not (agenda_url or minutes_url):
            self.logger.warning(
                f"{self.council_name}: no agenda or minutes recognised on {url}"
            )
            return None
        return ScraperReturn(
            name=name,
            date=summary["date"].isoformat(),
            time=summary["time"],
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )


# "Monday, June 30, 2025 - 07:00 PM": US order, so parsed with dayfirst off.
_LISTED = re.compile(
    r"(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})(?:\s*-\s*(?P<time>\d{1,2}:\d{2}\s*[AP]M))?"
)
_MEETING_PATH = re.compile(r"^/council-meetings/[a-z0-9-]+/[^/]+/\d+/?$")


def _summaries(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    summaries = []
    for block in soup.find_all("div", class_="council-meeting-summary"):
        link = block.find("a", href=_MEETING_PATH)
        when = block.find("p", class_="meeting-date")
        listed = _LISTED.search(when.get_text(" ", strip=True)) if when else None
        if not (link and listed):
            continue
        summaries.append(
            {
                "url": urljoin(SITE, link["href"]),
                "date": parse_date(listed.group("date")).date(),
                "time": (
                    parse_date(listed.group("time")).strftime("%I:%M %p").lstrip("0")
                    if listed.group("time")
                    else None
                ),
            }
        )
    return summaries


def _pager_target(html: str, page: int) -> Optional[str]:
    match = re.search(
        r"__doPostBack\(&#39;([^&]*dpMeetings[^&]*)&#39;,&#39;&#39;\)\">"
        rf"{page}</a>",
        html,
    )
    return match.group(1) if match else None


# A meeting page groups its files under <h3> headings. The Agenda group also
# holds late items ("10.6.1 - Shire Presence in Byford Town Centre") and
# motions on notice, so the agenda is the file in it whose title names the
# agenda, wherever the word falls: "Agenda - Ordinary Council Meeting - 16
# June 2025", "Ordinary Council Meeting Agenda - 16 November 2020". A title
# carrying an item number ("Ordinary Council Meeting - Agenda - 9.1 Motion
# on Notice") is that item's paper. The same goes for minutes ("Ordinary
# Council Meeting - 17 February 2020 - Minutes - CONFIRMED SIGNED"), where
# committee minutes turn up as numbered attachments.
_PAPER_TITLE = {
    "agenda": re.compile(r"\bagenda\b", re.IGNORECASE),
    "minutes": re.compile(r"\bminutes\b", re.IGNORECASE),
}
_NOT_THE_PAPER = re.compile(
    r"\b\d+\.\d+\b|attach|\blate\b|supplement|addend|motion|presentation",
    re.IGNORECASE,
)


def _is_paper(kind: str, title: str) -> bool:
    return bool(_PAPER_TITLE[kind].search(title)) and not _NOT_THE_PAPER.search(title)


def _papers(html: str, url: str) -> tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for heading in soup.select(".meeting-documents h3"):
        group = heading.get_text(" ", strip=True).lower()
        kind = (
            "agenda" if "agenda" in group else "minutes" if "minut" in group else None
        )
        if not kind or kind in found:
            continue
        summary = heading.find_next_sibling("blockquote")
        if not summary:
            continue
        for link in summary.find_all("a", href=True):
            title = re.sub(
                r"^Click to download\s+", "", link.get("title") or "", flags=re.I
            )
            if _is_paper(kind, title) and link["href"].lower().endswith(".pdf"):
                found[kind] = urljoin(url, link["href"])
                break
    return found.get("agenda"), found.get("minutes")
