import calendar
import datetime
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.meeting_documents import MINUTES
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
    _date_in_text,
)

_BASE_URL = "https://www.temora.nsw.gov.au"
_MEETINGS = f"{_BASE_URL}/Your-Council/Council-Meetings"
_OEMBED = "https://www.youtube.com/oembed"

# The words around a link's date that say nothing about the meeting: "Read
# the minutes from the February meeting", "View the agenda for the 15th
# October 2026 Ordinary Council Meeting.", "Action Minutes".
_FILLER = re.compile(
    r"\b(?:read|view|watch|the|minutes?|agenda|from|of|for|to|held|in|action"
    r"|meeting|council|ordinary|extra[\s-]*ordinary|special)\b|[.,]",
    re.IGNORECASE,
)

# "Extraordinary", "Extra Ordinary", "extra-ordinary", and one recording's
# "Exrtraordinary Meeting January 2022".
_EXTRAORDINARY = re.compile(r"\bex(?:tra|rtra)[\s-]*ordinary\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)

# A month section's heading on a Minutes-from-<year> page: "February 2026".
_MONTH_HEADING = re.compile(
    r"^\s*(?P<month>" + "|".join(calendar.month_name[1:]) + r")\s+(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)
_MONTH_NAME = re.compile(
    r"\b(?:" + "|".join(calendar.month_name[1:]) + r")\b", re.IGNORECASE
)

# "https://youtu.be/72-vBrLgWhc", "https://www.youtube.com/watch?v=2Xlttmdmiwc&t=3s",
# "youtube.com/watch?v=2QNi14rCWKA&list=...".
_VIDEO_ID = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^#]*&)?v=|live/|embed/))([\w-]{11})"
)

# oEmbed's answers for a recording that has no title to give: embedding
# turned off or the video private (401), deleted (404, 410). A fact about
# the video, so its meeting falls back to `misfiled` rather than failing
# the council. Anything else (403, 5xx, a timeout) still raises.
_NO_TITLE = frozenset({401, 404, 410})


def meeting_type(text: str) -> str:
    """Which kind of Council meeting a label or recording title names."""
    if _EXTRAORDINARY.search(text):
        return "Extraordinary Council Meeting"
    if _SPECIAL.search(text):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


@dataclass
class _Section:
    """One month's h2 section of a Minutes-from-<year> page."""

    year: int
    month: int
    recordings: list[str] = field(default_factory=list)  # YouTube video ids


def _status(error: requests.HTTPError) -> Optional[int]:
    if error.response is not None:
        return error.response.status_code
    # A replayed error keeps only its message: "401 Client Error: ...".
    m = re.match(r"(\d{3})\b", str(error))
    return int(m.group(1)) if m else None


@register_scraper
class TemoraScraper(OpenCitiesContentScraper):
    # Minutes on a page per year ("Minutes-from-2026", back to 2018), found
    # from the Past Council Minutes page, under an h2 per month ("May
    # 2026"); and the latest agenda alone on the Business Papers page. No
    # older agenda is online, so past meetings have minutes only. The
    # links are sentences ("Read the 21st May Ordinary Meeting Minutes",
    # "Read the minutes from the February meeting"), read here as the
    # meeting type, the paper and whatever date they give. The day is in
    # the label or the filename ("action-minutes-19012023.pdf") until
    # 2023; since then most links and files give only the month.
    #
    # Each such minutes file opens with the day ("Date: Thursday, 19
    # February 2026 Time: 4:00pm ... MINUTES Ordinary Council Meeting"), but
    # it is the whole business paper with its attachments, 5 to 210 MB, and
    # the server ignores Range requests and sends no length, so the first
    # page cannot be read without downloading the file. Reading 2026's eight
    # every night would cost about 360 MB, so `pdf_dates` is not used.
    #
    # Instead the day comes from the meeting's recording. Each month's
    # section links its YouTube video as well as its minutes ("Watch the
    # February meeting", "View the June 2026 Extraordinary Meeting
    # Livestream"), and YouTube's oEmbed endpoint gives the video's title,
    # which since February 2026 carries the full date: "19th February 2026
    # Ordinary Council Meeting", "9th June 2026 Extraordinary Council
    # Meeting". A month-only minutes takes the day of the one recording in
    # its own section whose title names the same meeting type (ordinary,
    # extraordinary or special; June 2026 held an ordinary and an
    # extraordinary meeting) and a date in the section's month and year
    # (`_date_from_recording`). Nothing else is
    # accepted: December 2023's section links January 2024's recording, and
    # most titles before 2026 give only the month ("Temora Shire Council
    # Meeting - August 2025"), as September 2026's does.
    #
    # Where no recording dates a minutes, `misfiled` may: the day its first
    # page gives, read once (26 Oct 2026) for each month-only minutes back
    # to 2020 that no recording dates. An entry wins over a recording,
    # since it was read off the paper itself, so only papers missing from
    # it cost an oEmbed request. A paper neither dates is left out, logged.
    #
    # Robots.txt on www.temora.nsw.gov.au disallows nothing under
    # /Your-Council/Council-Meetings or /files/, and sets no Crawl-delay.
    # www.youtube.com/robots.txt (read 26 Oct 2026) disallows 21 paths
    # for `User-agent: *`, "/api/", "/results", "/watch_ajax", "/youtubei/"
    # among them, and none is a prefix of /oembed; it sets no Crawl-delay.
    #
    # A 2026 run is three Temora pages and one oEmbed request per recording
    # in a section whose minutes give only the month: seven on 26 Oct 2026
    # (February, March, April, July and August, and June's two), 2 s apart
    # under the per-host throttle. Each later month adds one. Measured for
    # 2026 from a home IP on 26 Oct 2026: 10 requests, 11 meetings, 16 s
    # (three requests and 3.5 s before the recordings were read).
    expected_seconds = 16
    pages = [ContentPage(f"{_MEETINGS}/Business-Papers")]
    year_index = f"{_MEETINGS}/Past-Council-Minutes"
    year_page = re.compile(
        r"/Past-Council-Minutes/Minutes-from-(?P<year>\d{4})$", re.IGNORECASE
    )
    page_headings = ("h2",)
    # A year can hold minutes and no meeting with a day: 2024 had none, and
    # 2025 none before 16 October. Such a year raises rather than returning
    # nothing as if it were quiet.
    month_only_fails = True

    # Minutes labelled by month only, which no recording dates, dated from
    # their first page ("Date: Thursday, 19 February 2026 ... MINUTES
    # Ordinary Council Meeting 19 February 2026"), read once on 26 Oct 2026.
    # Every one was a Thursday. Ten more were read then and are dated by
    # their recordings now, each on the same day as its entry gave:
    # February 2020, June and July 2025, and February, March, April, June
    # (both meetings), July and August 2026.
    misfiled = {
        "action-minutes-january-2020.pdf": datetime.date(2020, 1, 16),
        "october-2020-action-minutes.pdf": datetime.date(2020, 10, 15),
        "november-2020-action-minutes.pdf": datetime.date(2020, 11, 19),
        # No recording linked.
        "march-2021-action-minutes.pdf": datetime.date(2021, 3, 18),
        # Linked only as "Read the Minutes" under "October 2021", and so
        # left out without a word until 26 Oct 2026; its cover reads "Date:
        # Thursday, 21 October 2021 ... MINUTES Ordinary Council Meeting 21
        # October 2021".
        "october-2021-action-minutes.pdf": datetime.date(2021, 10, 21),
        "november-2021-action-minutes.pdf": datetime.date(2021, 11, 18),
        "july-2022-action-minutes.pdf": datetime.date(2022, 7, 21),
        "august-2022-action-minutes.pdf": datetime.date(2022, 8, 18),
        "december-2022-action-minutes.pdf": datetime.date(2022, 12, 15),
        "february-2023-action-minutes.pdf": datetime.date(2023, 2, 16),
        "may-2023-action-minutes.pdf": datetime.date(2023, 5, 18),
        "july-2023-action-minutes.pdf": datetime.date(2023, 7, 20),
        "august-2023-action-minutes.pdf": datetime.date(2023, 8, 17),
        # Its recording answers oEmbed with 401.
        "september-2023-action-minutes.pdf": datetime.date(2023, 9, 21),
        "october-2023-action-minutes.pdf": datetime.date(2023, 10, 19),
        "november-2023-action-minutes.pdf": datetime.date(2023, 11, 30),
        # Its section links January 2024's recording.
        "december-2023-action-minutes.pdf": datetime.date(2023, 12, 21),
        "january-2024-action-minutes.pdf": datetime.date(2024, 1, 18),
        "february-2024-action-minutes.pdf": datetime.date(2024, 2, 15),
        "march-2024-action-minutes.pdf": datetime.date(2024, 3, 21),
        "april-2024-action-minutes.pdf": datetime.date(2024, 4, 18),
        "may-2024-action-minutes.pdf": datetime.date(2024, 5, 16),
        "june-2024-action-minutes.pdf": datetime.date(2024, 6, 20),
        "july-2024-action-minutes.pdf": datetime.date(2024, 7, 18),
        "august-2024-action-minutes.pdf": datetime.date(2024, 8, 15),
        "november-2024-action-minutes.pdf": datetime.date(2024, 11, 28),
        "december-2024-action-minutes.pdf": datetime.date(2024, 12, 19),
        "january-2025-action-minutes.pdf": datetime.date(2025, 1, 16),
        "february-2025-action-minutes.pdf": datetime.date(2025, 2, 20),
        "march-2025-action-minutes.pdf": datetime.date(2025, 3, 20),
        "april-2025-action-minutes.pdf": datetime.date(2025, 4, 17),
        "may-2025-action-minutes.pdf": datetime.date(2025, 5, 15),
        "august-2025-action-minutes.pdf": datetime.date(2025, 8, 21),
        "september-2025-action-minutes.pdf": datetime.date(2025, 9, 18),
        "november-2025-action-minutes.pdf": datetime.date(2025, 11, 20),
        "december-2025-action-minutes.pdf": datetime.date(2025, 12, 18),
        # Its recording is titled "Temora Shire Council Meeting - September
        # 2026", with no day.
        "september-2026-action-minutes.pdf": datetime.date(2026, 9, 17),
    }

    def __init__(self):
        super().__init__("temora", "NSW", _BASE_URL)
        # Each document's month section, by URL, and each video's title.
        self._sections: dict[str, _Section] = {}
        self._titles: dict[str, Optional[str]] = {}

    def link_label(self, a: Tag, label: str) -> Optional[str]:
        stem = unquote(urlparse(a.get("href", "")).path.rsplit("/", 1)[-1])
        words = f"{label} {stem.replace('-', ' ').replace('_', ' ')}"
        # "action-agenda-16072020.pdf", linked as "View the minutes from the
        # July 2020 meeting", is the agenda: its PDF opens "I hereby give
        # notice ... AGENDA Ordinary Council Meeting 16 July 2020". The
        # minutes are "...-action-minutes...".
        if re.search(r"\bagenda\b", label, re.IGNORECASE) or stem.lower().startswith(
            "action-agenda"
        ):
            paper = "Agenda"
        elif re.search(r"\bminutes?\b", label, re.IGNORECASE):
            paper = "Minutes"
        else:
            # "Planning Report January 2023".
            return None
        meeting = meeting_type(words)
        when = re.sub(r"\s+", " ", _FILLER.sub(" ", label)).strip()
        if not _MONTH_NAME.search(when):
            # "Read the minutes", under "May 2025": the month is the
            # section's, so a paper published that way is still read as
            # month-only, for a recording or `misfiled` to date.
            heading = a.find_previous("h2")
            if heading and _MONTH_HEADING.match(heading.get_text(" ", strip=True)):
                when = f"{when} {heading.get_text(' ', strip=True)}".strip()
        return f"{meeting} - {paper} - {when}".rstrip(" -")

    # --- recordings ---------------------------------------------------------

    def _links(self, html: str, page_url: str):
        self._read_sections(html, page_url)
        return super()._links(html, page_url)

    def _read_sections(self, html: str, page_url: str) -> None:
        """Note each document's month section and the recordings it links."""
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one(self.content_selector) or soup
        section: Optional[_Section] = None
        for el in content.find_all(["h2", "a"]):
            if el.name == "h2":
                m = _MONTH_HEADING.match(el.get_text(" ", strip=True))
                section = (
                    _Section(
                        int(m["year"]),
                        list(calendar.month_name).index(m["month"].capitalize()),
                    )
                    if m
                    else None
                )
                continue
            href = el.get("href", "")
            if section is None or not href:
                continue
            video = _VIDEO_ID.search(href)
            if video:
                if video.group(1) not in section.recordings:
                    section.recordings.append(video.group(1))
            elif self._is_document(href):
                self._sections[urljoin(page_url, href)] = section

    def date_month_only(self, papers, wanted):
        dated = []
        for paper in papers:
            if paper.kind != MINUTES or paper.month is None:
                continue
            if wanted and paper.year not in wanted:
                continue
            date = self._date_from_recording(paper, papers)
            if date:
                self.logger.info(
                    f"{self.council_name}: {paper.link.label!r} dated {date} "
                    f"from its recording's title"
                )
                paper.date = date
                dated.append(paper)
        return dated

    def _date_from_recording(self, paper, papers) -> Optional[datetime.date]:
        """The day of the one recording in the paper's section that matches it.

        A recording matches when its title names the paper's meeting type
        and a full date in the section's month and year. None when the
        section links no such recording, or more than one date fits, or
        another month-only minutes of the same type shares the section.
        """
        section = self._sections.get(paper.link.url)
        if section is None:
            return None
        where = f"{calendar.month_name[section.month]} {section.year}"
        if (paper.year, paper.month) != (section.year, section.month):
            self.logger.info(
                f"{self.council_name}: {paper.link.label!r} is under {where}; "
                f"not dating it from that month's recordings"
            )
            return None
        kind = meeting_type(paper.link.label)
        if any(
            p is not paper
            and p.kind == MINUTES
            and self._sections.get(p.link.url) is section
            and meeting_type(p.link.label) == kind
            for p in papers
        ):
            self.logger.info(
                f"{self.council_name}: two month-only {kind} minutes under "
                f"{where}; not dating either from a recording"
            )
            return None
        dates = set()
        for video in section.recordings:
            title = self._recording_title(video)
            if title is None or meeting_type(title) != kind:
                continue
            found = _date_in_text(title, None)
            if found is None or found.date is None:
                continue
            if (found.date.year, found.date.month) != (section.year, section.month):
                self.logger.info(
                    f"{self.council_name}: recording {video} under {where} is "
                    f"titled {title!r}; not using it"
                )
                continue
            dates.add(found.date)
        if len(dates) == 1:
            return dates.pop()
        if dates:
            self.logger.info(
                f"{self.council_name}: recordings under {where} give "
                f"{sorted(dates)} for {paper.link.label!r}; not choosing"
            )
        return None

    def _recording_title(self, video: str) -> Optional[str]:
        """The video's title from YouTube's oEmbed endpoint, fetched once."""
        if video in self._titles:
            return self._titles[video]
        query = urlencode(
            {"url": f"https://www.youtube.com/watch?v={video}", "format": "json"}
        )
        title = None
        try:
            body = self.fetcher.fetch_with_requests(f"{_OEMBED}?{query}")
        except requests.HTTPError as e:
            if _status(e) not in _NO_TITLE:
                raise
            self.logger.warning(
                f"{self.council_name}: recording {video} gives no title: {e}"
            )
        else:
            try:
                title = json.loads(body)["title"]
            except (ValueError, KeyError, TypeError) as e:
                raise RuntimeError(
                    f"{self.council_name}: oEmbed for {video} is not a title: "
                    f"{body[:120]!r}"
                ) from e
        self._titles[video] = title
        return title
