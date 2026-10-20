import datetime
import re
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wiluna.wa.gov.au"
_WEBPAGE_URL = f"{_BASE_URL}/documents/?path=%2fPublic%2fCouncil+and+Committee+Agendas"

# The council's document centre is a React app (public.wiluna.wa.gov.au)
# iframed into the CouncilConnect site. It lists a SharePoint library, and
# each file's link (`LinkToItem`) is that file's copy in a public Azure blob
# container. The SharePoint API is not an option—sharepoint.com's robots.txt
# is `Disallow: /`—but the container allows anonymous listing, and one list
# call returns every agenda and minutes file with its folder.
_CONTAINER = "https://sowcrpublic.blob.core.windows.net/cr-public"
_PREFIX = "Public/Council and Committee "
_LIST_URL = f"{_CONTAINER}?restype=container&comp=list&prefix={quote(_PREFIX)}"

# Only the year folders the document centre shows. The container also keeps
# folders SharePoint has since dropped ("OCM Agendas 2019", "OCM and SCM
# Agendas 2021", "Council and Committee Minutes/2019", a misspelt
# "Ordnary and Special ... 2024"), which repeat the same papers.
_FOLDER = re.compile(
    r"^Public/Council and Committee (?:Agendas|Minutes)/"
    r"(?P<body>Ordinary and Special Council Meeting"
    r"|Audit, Risk and Improvement Committee) (?:Agendas|Minutes) "
    r"(?P<year>\d{4})/(?P<file>[^/]+)$"
)

# "2025.01.28 Ordinary Meeting of Council - Agenda.pdf", and in 2020 also
# "OCM 20201216 Unconfirmed Minutes.pdf".
_FILE_DATE = re.compile(r"(?<!\d)(20\d\d)\.?(\d{1,2})\.?(\d{1,2})(?!\d)")

# Files that sit beside the agenda and minutes but are neither: attachment
# books ("Agenda Attachments", "Minute Attachments", "Minutes - Attachments
# Excluding Confidential"), recordings, public notices. "Agenda with
# attachments" and "Agenda Combined" are the agenda itself and stay.
_ATTACHMENTS = re.compile(
    r"(?:agenda|minutes?)\s*-?\s*attachments|meeting\s*-\s*attachments",
    re.IGNORECASE,
)
_NOT_PAPERS = re.compile(r"recording|notice", re.IGNORECASE)
_CONFIDENTIAL = re.compile(r"(?<!excluding )confidential", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_AUDIT = re.compile(r"\baudit\b|\bARIC\b", re.IGNORECASE)
_ELECTORS = re.compile(r"\belectors?\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b|\bSCM\b", re.IGNORECASE)

# Minutes appear in several versions per meeting. Confirmed beats signed
# (the same text, scanned) beats a bare "Minutes", which beats unconfirmed.
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_SIGNED = re.compile(r"\bsigned\b", re.IGNORECASE)

# An agenda's filename is sometimes the date the CEO signed the notice paper
# rather than the meeting's: "2024.06.20 Ordinary Meeting of Council -
# Agenda.pdf" calls the meeting for Monday 24 June, and the minutes are
# filed as 2024.06.24. An agenda with no minutes of its own is joined to the
# next minutes-only meeting of the same body within this many days, and the
# minutes' date is kept.
_NOTICE_LEAD_DAYS = 7


# A year's folders appear with its first papers, in late January (28
# January 2026 and 2025), so for its first weeks the current year is empty. An empty year is an error only once this much of it has passed,
# the rule CraftMeetingsModuleScraper uses.
_NEW_YEAR_GRACE_DAYS = 90


def _owed_papers(year: int) -> bool:
    """Whether a year has run long enough that it must have papers."""
    today = clock.today()
    return year < today.year or (
        year == today.year
        and (today - datetime.date(year, 1, 1)).days >= _NEW_YEAR_GRACE_DAYS
    )


@register_scraper
class WilunaScraper(BaseScraper):
    def __init__(self):
        super().__init__("wiluna", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _blobs(self) -> list[tuple[str, str]]:
        """(name, last-modified) for every blob under the prefix."""
        blobs = []
        marker = None
        while True:
            url = _LIST_URL + (f"&marker={quote(marker)}" if marker else "")
            # The listing starts with a byte-order mark, which ElementTree
            # rejects as content before the XML declaration.
            xml = self.fetcher.fetch_with_requests(url).lstrip("﻿")
            root = ElementTree.fromstring(xml)
            for blob in root.iter("Blob"):
                blobs.append(
                    (blob.findtext("Name"), blob.findtext("Properties/Last-Modified"))
                )
            marker = root.findtext("NextMarker")
            if not marker:
                return blobs

    @staticmethod
    def _rank(kind: str, file: str) -> int:
        if kind == "agenda":
            return 0 if not re.search(r"attach|combined", file, re.I) else 1
        if _UNCONFIRMED.search(file):
            return 3
        if _CONFIRMED.search(file):
            return 1 if _SIGNED.search(file) else 0
        return 2

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # (date, name) -> kind -> (rank, -modified, url)
        meetings: dict[tuple, dict] = {}
        listed = 0
        for name, modified in self._blobs():
            match = _FOLDER.match(name or "")
            if not match:
                continue
            listed += 1
            file = match["file"]
            if not file.lower().endswith(".pdf"):
                continue
            if _ATTACHMENTS.search(file) or _NOT_PAPERS.search(file):
                continue
            if _CONFIDENTIAL.search(file):
                continue
            date_match = _FILE_DATE.search(file)
            if not date_match:
                continue
            try:
                date = datetime.date(*(int(g) for g in date_match.groups()))
            except ValueError:
                continue
            # A year that disagrees with the folder is a typo: the 2020
            # minutes folder holds "2023.09.23 ..." and "2023.11.25 ...",
            # re-uploads of the 2020 meetings of those days, and the 2022
            # ARIC folders a "2021.03.14" copy of 14 March 2022. The real
            # meeting is always in its own year's folder too.
            if date.year != int(match["year"]) or date.year not in wanted:
                continue

            if _MINUTES.search(file):
                kind = "minutes"
            elif _AGENDA.search(file):
                kind = "agenda"
            else:
                continue

            # The folder is not always right about the body either: the
            # 2025 Council minutes folder holds an ARIC minutes file and the
            # electors' meeting of 25 February 2025, the same day as an
            # ordinary meeting. Electors' meetings have a folder of their own
            # that this scraper does not read, so a stray one is dropped.
            if _ELECTORS.search(file):
                continue
            special = bool(_SPECIAL.search(file))
            if match["body"].startswith("Audit") or _AUDIT.search(file):
                body = "Audit, Risk and Improvement Committee Meeting"
            else:
                body = "Council Meeting"
                if not special:
                    body = "Ordinary " + body
            if special:
                body = "Special " + body

            # Ties go to the newest upload: in March 2026 the library was
            # re-synced and the copies it shows now carry that date.
            stamp = -parsedate_to_datetime(modified).timestamp()
            candidate = (self._rank(kind, file), stamp, _CONTAINER + "/" + quote(name))
            slots = meetings.setdefault((date, body), {})
            if kind not in slots or candidate < slots[kind]:
                slots[kind] = candidate

        self._join_notice_dated_agendas(meetings)

        results = []
        for (date, body), slots in sorted(meetings.items()):
            agenda_url = slots["agenda"][2] if "agenda" in slots else None
            minutes_url = slots["minutes"][2] if "minutes" in slots else None
            results.append(
                ScraperReturn(
                    name=body,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_WEBPAGE_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not listed:
            # One request carries every year, so no files in the year
            # folders at all is the listing changing shape, whatever the
            # date.
            raise RuntimeError(
                f"{self.council_name}: no files in the year folders of {_LIST_URL}"
            )
        if not results and any(_owed_papers(y) for y in wanted):
            raise RuntimeError(
                f"{self.council_name}: no agendas or minutes in {_LIST_URL} for "
                f"{sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _join_notice_dated_agendas(meetings: dict[tuple, dict]) -> None:
        agenda_only = [k for k, v in meetings.items() if set(v) == {"agenda"}]
        for date, body in sorted(agenda_only):
            for offset in range(1, _NOTICE_LEAD_DAYS + 1):
                later = (date + datetime.timedelta(days=offset), body)
                if set(meetings.get(later, {})) == {"minutes"}:
                    meetings[later]["agenda"] = meetings.pop((date, body))["agenda"]
                    break
