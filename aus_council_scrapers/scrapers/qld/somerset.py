import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper

# The council's meetings page frames the Resolve portal, and under it keeps
# "Previous Minutes and Agendas": every PDF before the move, in two flat
# lists of links.
COUNCIL_MEETINGS = "https://www.somerset.qld.gov.au/Your-Council/Council-Meetings"


@register_scraper
class SomersetScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP in a full
    # 135-council run at 10 workers: 43 s, most of it queued behind the
    # other tenants on api.resolve.red (10 s alone). Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 43

    # Somerset moved to Resolve for its 12 November 2025 Ordinary meeting.
    # Earlier papers are direct PDF links on the council's Council-Meetings
    # page (minutes from 2016, agendas from April 2023), read by
    # `other_meetings` in one request. So meetings from 2020 to March 2023
    # have minutes but no agenda: the council never posted those agendas.
    tenant = "somerset"
    resolve_from = datetime.date(2025, 11, 12)

    # Ordinary Council is the tenant's only meeting type. Naming it keeps a
    # committee the council starts publishing here from adding a request
    # per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^Ordinary Council$")

    def __init__(self):
        super().__init__("somerset", "QLD")

    def _record(self, event, today) -> Optional[ScraperReturn]:
        record = super()._record(event, today)
        if record and record.location:
            # One meeting's location field carries a cultural warning for
            # its recording, with the venue after "Location:".
            _, _, venue = record.location.rpartition("Location:")
            record.location = venue.strip() or None
        return record

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = {year for year in self.before_resolve(wanted) if year >= EARLIEST_YEAR}
        if not years:
            return []
        html = self.fetcher.fetch_with_requests(COUNCIL_MEETINGS)
        meetings = _archive(html)
        if not meetings:
            raise RuntimeError(
                f"{self.council_name}: no past agendas or minutes on {COUNCIL_MEETINGS}"
            )
        return [
            meeting
            for meeting in meetings
            if int(meeting.date[:4]) in years
            and datetime.date.fromisoformat(meeting.date) < self.resolve_from
        ]


# A link's title is the file's name as the council typed it: "2025_10_29
# Ordinary AGENDA Volume 1", "2024-02-21 Ordinary Minutes", "2022 03 23
# Ordinary Minutes", "2025_06_18 Special Meeting (Budget) Minutes".
_TITLE = re.compile(r"^(\d{4})[ _-](\d{2})[ _-](\d{2})[ _-]*(.*)$")

# A big agenda is split into volumes, of which only the first holds the
# agenda itself; later volumes, and the "Part 2" of a split set of minutes,
# are its attachments. Notices of a special meeting, appendices and
# attachments are not the agenda or the minutes either.
_LATER_VOLUME = re.compile(
    r"\b(?:vol(?:ume)?|part)[\s_-]*0*([2-9]|\d{2,})\b", re.IGNORECASE
)
_NOT_THE_PAPER = re.compile(r"notice|appendix|attachment|resolutions", re.IGNORECASE)

# Somerset's own words for its meetings: ordinary, special (budget
# adoption included), and the statutory post-election meeting. The names
# match the Resolve tenant's, where it has the meeting.
_POST_ELECTION = re.compile(r"post.election|statutory", re.IGNORECASE)
_SPECIAL = re.compile(r"special|budget", re.IGNORECASE)


def _archive(html: str) -> list[ScraperReturn]:
    soup = BeautifulSoup(html, "html.parser")
    papers: dict[tuple[str, str], dict[str, str]] = {}
    for link in soup.find_all("a", class_="document", href=True):
        if not link["href"].lower().endswith(".pdf"):
            continue
        match = _TITLE.match((link.get("title") or "").strip())
        if not match:
            continue
        year, month, day, rest = match.groups()
        if _NOT_THE_PAPER.search(rest) or _LATER_VOLUME.search(rest):
            continue
        if re.search(r"\bagenda\b", rest, re.IGNORECASE):
            kind = "agenda"
        elif re.search(r"\bminutes\b", rest, re.IGNORECASE):
            kind = "minutes"
        else:
            continue

        if _POST_ELECTION.search(rest):
            name = "Post-Election Meeting"
        elif _SPECIAL.search(rest) and not re.search(r"ordinary", rest, re.IGNORECASE):
            name = "Special Council"
        else:
            name = "Ordinary Council"

        # Where the council re-uploaded a corrected volume ("2025_01_22
        # Ordinary Agenda Volume 1" is listed twice, the second file named
        # -v2), the later link on the page is the replacement.
        date = f"{year}-{month}-{day}"
        papers.setdefault((date, name), {})[kind] = urljoin(
            COUNCIL_MEETINGS, link["href"]
        )

    return [
        ScraperReturn(
            name=name,
            date=date,
            time=None,
            webpage_url=COUNCIL_MEETINGS,
            agenda_url=found.get("agenda"),
            minutes_url=found.get("minutes"),
            download_url=found.get("agenda") or found.get("minutes"),
        )
        for (date, name), found in sorted(papers.items())
    ]
