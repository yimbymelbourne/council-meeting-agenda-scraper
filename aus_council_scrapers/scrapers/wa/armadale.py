import datetime
import json
import re
from collections import Counter
from typing import Optional
from urllib.parse import urljoin

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = "https://my.armadale.wa.gov.au/service/agendas-and-minutes/"

# The listing is a Next.js page over Contentful, prerendered and served from
# S3. Every one of the ~4,000 documents back to 2000 is embedded in that one
# page as the React Server Components "flight" payload—`self.__next_f.push`
# calls holding JSON-in-a-string—under `prefetchedData.councilMeetingDocument`.
# So the page is 8 MB, and it is also the only request: the old archive hosts
# (www.armadale.wa.gov.au/agendas-minutes-archive, info.armadale.wa.gov.au)
# now 404, and the browser never queries Contentful itself.
_FLIGHT_CHUNK = re.compile(r"self\.__next_f\.push\(\[1,")
_DOCUMENTS_KEY = '"councilMeetingDocument":['

# Each entry is one document, not one meeting: a title ("Ordinary Council
# Meeting Minutes 12 Oct 2026"), a meetingType, a documentType and a
# publicationDate, which is the meeting date—it matches the date in the file
# name ("2026-10-12 - Minutes - Ordinary Meeting of Council.pdf").
#
# The title and the file name each state the date as well, and all three are
# typed by hand. They disagree on 27 of the 3,990 entries. Usually the file
# name is the odd one out—a stale year carried over from an older file
# ("22 november 2202", "28 january 2019" for a 2020 meeting)—but not always:
# the Technical Services agenda of 6 March 2024 has publicationDate
# 2024-04-06, day and month swapped, while its title and file say 6 March,
# and leaving it there splits it from its minutes. So the majority of the
# three decides (see `_meeting_date`); that moves that one document and no
# other. A vote cannot catch an error made in two places: Technical Services
# "25 Aug 2024" has that date in both title and publicationDate, but it is a
# Sunday, and its files and the agenda's front page say Monday 5 August. So a
# weekend winner yields to a file-name date that is a weekday in the same
# month and year. Across the whole archive that moves those two papers and
# nothing else: the only other weekend-dated paper, a 3 November 2007
# cancellation notice, has no weekday date to move to.
_ISO_DATE = re.compile(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b")
_WRITTEN_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()

# documentType is sometimes wrong where the title is right: "Ordinary Council
# Meeting Minutes 28 Jul 2025" is filed as an Agenda, which made that
# meeting's minutes a second agenda. So the title decides, and documentType
# only breaks a tie.
_MINUTES = re.compile(r"\bmin(?:ute|tue)s\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_DOCUMENT_TYPES = {"agenda": "agenda", "minutes": "minutes"}

# An entry can carry several files: the agenda plus a separately bound
# budget or strategy, or—for a meeting called off—a cancellation notice in
# the agenda's place. The meeting's own document is the one named as an
# agenda or minutes.
_NOT_THE_DOCUMENT = re.compile(r"attach|cancel|report|separate", re.IGNORECASE)

# Two meetings of one body on one night ("Special Council Meeting 7pm" and
# "8pm", 21 October 2019) are told apart only by a time in the file name.
_TIME = re.compile(r"(?<![\d.])(\d{1,2})(?:[.:](\d{2}))?\s*([ap])\.?m\b", re.IGNORECASE)

# Committee meeting types are bare names ("Development Services", "City
# Audit"), where the documents themselves say "Development Services
# Committee".
_ALREADY_NAMED = re.compile(r"council|meeting|committee|panel|electors", re.IGNORECASE)


def _meeting_name(meeting_type: str) -> str:
    name = re.sub(r"\s+", " ", meeting_type).strip()
    name = re.sub(r"\bmeeting of electors\b", "Meeting of Electors", name, flags=re.IGNORECASE)
    if not _ALREADY_NAMED.search(name):
        name = f"{name} Committee"
    return name


@register_scraper
class ArmadaleScraper(BaseScraper):
    # One production year, measured 19 Oct 2026 from a home IP in full
    # 135-council runs: 19.5 s at 10 workers, 13.7 s at 6. Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 20

    def __init__(self):
        super().__init__("armadale", "WA", "https://my.armadale.wa.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _documents(self, page: str) -> list:
        decoder = json.JSONDecoder()
        flight = "".join(
            decoder.raw_decode(page, match.end())[0]
            for match in _FLIGHT_CHUNK.finditer(page)
        )
        start = flight.find(_DOCUMENTS_KEY)
        if start < 0:
            return []
        documents, _ = decoder.raw_decode(flight, start + len(_DOCUMENTS_KEY) - 1)
        return documents

    @staticmethod
    def _kind(fields: dict) -> Optional[str]:
        title = fields.get("title") or ""
        if _MINUTES.search(title):
            return "minutes"
        if _AGENDA.search(title):
            return "agenda"
        return _DOCUMENT_TYPES.get((fields.get("documentType") or "").lower())

    @staticmethod
    def _main_file(fields: dict) -> Optional[dict]:
        for asset in fields.get("document") or []:
            asset_fields = asset.get("fields") or {}
            file = asset_fields.get("file") or {}
            # File names use underscores ("agenda_-_technical_services"),
            # which \b does not treat as a break.
            label = f"{asset_fields.get('description') or ''} {file.get('fileName') or ''}"
            label = label.replace("_", " ")
            if not file.get("url") or file.get("contentType") != "application/pdf":
                continue
            if _NOT_THE_DOCUMENT.search(asset_fields.get("description") or ""):
                continue
            if _AGENDA.search(label) or _MINUTES.search(label):
                return {**file, "title": asset_fields.get("title") or ""}
        return None

    @staticmethod
    def _written_date(text: str) -> Optional[str]:
        text = text.replace("_", " ")
        match = _ISO_DATE.search(text)
        if match:
            parts = tuple(map(int, match.groups()))
        else:
            match = _WRITTEN_DATE.search(text)
            if not match:
                return None
            day, month, year = match.groups()
            parts = (int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
        try:
            return datetime.date(*parts).isoformat()
        except ValueError:
            return None

    def _meeting_date(self, published: str, title: str, file_name: str) -> str:
        votes = Counter(
            d
            for d in (published, self._written_date(title), self._written_date(file_name))
            if d
        )
        best, count = votes.most_common(1)[0]
        best = best if count > 1 else published
        from_file = self._written_date(file_name)
        if (
            from_file
            and datetime.date.fromisoformat(best[:10]).weekday() >= 5
            and datetime.date.fromisoformat(from_file).weekday() < 5
            and from_file[:7] == best[:7]
        ):
            return from_file
        return best

    @staticmethod
    def _time(*texts: str) -> Optional[str]:
        for text in texts:
            match = _TIME.search(text.replace("_", " "))
            if match:
                hour, minute, half = match.groups()
                return f"{int(hour)}:{minute or '00'} {half.upper()}M"
        return None

    @staticmethod
    def _slots(papers: list) -> list[dict]:
        """Sort one body's papers for one date into meetings.

        Nearly always that is one meeting. When a body met twice in a night,
        the files say which is which by time ("special_council_meeting_8pm"),
        so the timed papers are placed first, one meeting per time. Each
        untimed paper then joins the earliest meeting still missing that kind
        of paper: Special Council on 21 October 2019 has an "8pm" agenda, an
        unlabelled agenda, and "7pm" and "8pm" minutes, which makes the
        unlabelled agenda the 7pm meeting's. A second untimed copy of a paper
        every meeting already has is a duplicate upload, and is dropped.
        """
        slots: list[dict] = []
        for kind, url, time in sorted(papers, key=lambda p: p[2] is None):
            if time:
                slot = next((s for s in slots if s["time"] == time), None)
            else:
                open_slots = [s for s in slots if s[kind] is None]
                open_slots.sort(key=lambda s: _sortable_time(s["time"]))
                slot = open_slots[0] if open_slots else None
                if slot is None and slots:
                    continue
            if slot is None:
                slot = {"time": time, "agenda": None, "minutes": None}
                slots.append(slot)
            if slot[kind] is None:
                slot[kind] = url
        return slots

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        documents = self._documents(self.fetcher.fetch_with_requests(_LISTING_URL))
        # Raise rather than return []: an empty list counts as a working
        # council in the nightly run, which would hide a page that changed.
        if not documents:
            raise RuntimeError(
                f"{self.council_name}: no councilMeetingDocument entries in the "
                f"flight payload of {_LISTING_URL}—the page has probably changed shape"
            )

        wanted = self._wanted_years()
        # (name, date) -> [(kind, url, time)], in listing order
        papers: dict[tuple, list] = {}

        for document in documents:
            fields = document.get("fields") or {}
            published = fields.get("publicationDate") or ""
            # Development Assessment Panel entries link to a search on the
            # state planning portal rather than to a document.
            if not published or fields.get("externalUrl"):
                continue
            kind = self._kind(fields)
            file = self._main_file(fields) if kind else None
            if not file:
                continue
            date = self._meeting_date(
                published, fields.get("title") or "", file.get("fileName") or ""
            )
            if int(date[:4]) not in wanted:
                continue

            name = _meeting_name(fields.get("meetingType") or "Council Meeting")
            url = urljoin("https:", file["url"])
            time = self._time(
                file.get("fileName") or "", file["title"], fields.get("title") or ""
            )
            papers.setdefault((name, date), []).append((kind, url, time))

        results = []
        for (name, date), meeting_papers in papers.items():
            for slot in self._slots(meeting_papers):
                agenda_url, minutes_url = slot["agenda"], slot["minutes"]
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date,
                        time=slot["time"],
                        webpage_url=_LISTING_URL,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results


def _sortable_time(time: Optional[str]) -> tuple:
    if not time:
        return (99, 0)
    clock_part, half = time.split(" ")
    hour, minute = map(int, clock_part.split(":"))
    return ((hour % 12) + (12 if half == "PM" else 0), minute)
