import re
import urllib.parse
from typing import Optional

from aus_council_scrapers.base import (
    DocsPublishedScraper,
    ScraperReturn,
    register_scraper,
)

# What the council's filenames wrap around the meeting type: "Agenda - Audit
# and Risk Committee Meeting - 4 March 2025.pdf", "public Final Minutes for
# Audit Committee Meeting 03 12 2024.pdf".
_FILE_PREFIX = re.compile(
    r"^(?:public\s+)?(?:final\s+)?(?:agenda|minutes)(?:\s+for)?\s*-?\s*", re.I
)
_FILE_DATE = re.compile(
    r"\s*-?\s*\d{1,2}[\s/.-]+(?:\d{1,2}|[A-Za-z]+)[\s/.-]+\d{4}\s*$"
)
_MEETING_WORDS = re.compile(r"\b(?:Meeting|Committee|Council)\b", re.I)


@register_scraper
class GosnellsScraper(DocsPublishedScraper):
    # gosnells.wa.gov.au is OpenCities, which is why detect_platform reports
    # it as Granicus; its "Agenda and Minutes Portal" link goes here. Agendas
    # start in 2025—the archive back to 2001 was uploaded as minutes only—
    # so older meetings come out as minutes-only records.
    publishing_slug = "gosnellscitycouncil"

    def __init__(self):
        super().__init__("gosnells", "WA")

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()

        # Five records have no meeting type, so the base class names them
        # from a DocumentTitle of " - Tuesday 4 March 2025" or "Unspecified -
        # ...". Four are second uploads of an Audit and Risk Committee
        # meeting that is also listed on the same date under its proper
        # type, and one of them holds the only copy of that agenda. So an untyped
        # record lends its documents to the typed one and is dropped; one
        # with no typed twin is kept, named from its filename.
        typed = [m for m in results if not self._untyped(m)]
        kept = []
        for meeting in results:
            if not self._untyped(meeting):
                kept.append(meeting)
                continue
            meeting.name = self._name_from_file(
                meeting.agenda_url or meeting.minutes_url
            )
            twin = self._twin(meeting, typed)
            if twin is None:
                kept.append(meeting)
                continue
            for field in ("agenda_url", "minutes_url"):
                if not getattr(twin, field):
                    setattr(twin, field, getattr(meeting, field))
            twin.download_url = twin.agenda_url or twin.minutes_url

        for meeting in kept:
            self._tidy(meeting)
        return kept

    @staticmethod
    def _twin(meeting: ScraperReturn, typed: list[ScraperReturn]):
        same_day = [m for m in typed if m.date == meeting.date]
        named = [
            m
            for m in same_day
            if meeting.name and m.name and meeting.name.lower() == m.name.lower()
        ]
        if len(named) == 1:
            return named[0]
        return same_day[0] if len(same_day) == 1 else None

    @staticmethod
    def _untyped(meeting: ScraperReturn) -> bool:
        name = (meeting.name or "").strip()
        return not name or name.startswith(("-", "Unspecified"))

    def _tidy(self, meeting: ScraperReturn) -> None:
        # Archive records are stamped at local midnight: they carry a date
        # and no time, and "12:00 AM" would claim one.
        if meeting.time == "12:00 AM":
            meeting.time = None

        # 10 August 2021 was cancelled by a power outage, and its agenda was
        # uploaded into the minutes slot ("OCM Agenda 100821 Merged.pdf").
        # A file named as an agenda and not as minutes is an agenda.
        filename = self._filename(meeting.minutes_url)
        if (
            not meeting.agenda_url
            and re.search(r"\bagenda\b", filename, re.I)
            and not re.search(r"minute", filename, re.I)
        ):
            meeting.agenda_url, meeting.minutes_url = meeting.minutes_url, None
            meeting.download_url = meeting.agenda_url

    @staticmethod
    def _filename(url: Optional[str]) -> str:
        if not url:
            return ""
        return urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])

    def _name_from_file(self, url: Optional[str]) -> Optional[str]:
        stem = re.sub(r"\.pdf$", "", self._filename(url), flags=re.I)
        name = _FILE_DATE.sub("", _FILE_PREFIX.sub("", stem)).strip(" -")
        # "007 F 819 C.002.pdf" says nothing; no name beats a wrong one.
        return name if _MEETING_WORDS.search(name) else None
