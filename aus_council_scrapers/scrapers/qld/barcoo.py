import datetime
import re
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_PORTAL = "https://myportal.barcoo.qld.gov.au"
_PUBLICATIONS_URL = f"{_PORTAL}/public/publications"

# barcoo.qld.gov.au's "Meeting agendas and minutes" page only points here:
# the council's ratepayer portal, an ASP.NET WebForms folder browser over its
# records system. There is no page per folder. Opening one is a postback—a
# form POST carrying __VIEWSTATE and __EVENTVALIDATION from the previous
# response—so each step is read off the page the last step returned:
#
#   1. GET the portal: two root folders, "Council Agendas" (ctrl0) and
#      "Council Minutes" (ctrl1).
#   2. Post that root's ExpandFolders: its year folders appear in the tree
#      as FolderTree postbacks with arguments like "s2026".
#   3. Post FolderTree for a year: the year's files are listed as
#      /download/<id>/<hash> links.
#
# Minutes years also hold an "Unconfirmed Minutes" subfolder ("s2026\
# Unconfirmed Minutes"), where a meeting's minutes sit until the next meeting
# confirms them and they move up into the year folder.
#
# Files are named for the meeting: "2026 05 20 Agenda May Ordinary
# Meeting.pdf", "2023-06-28 Special Meeting.pdf", "2026 09 16 September
# Confirmed Ordinary Meeting Minutes.pdf". The date leads every name.
#
# One production year is six requests: the portal, two expands, two year
# folders and the unconfirmed subfolder. The portal has no robots.txt (404).
#
# The <hash> in a download link changes with every session, and the portal
# ignores it: /download/<id>/0, /download/<id>/file and a hash of 32 zeros
# all serve the same PDF, while /download/<id> with no hash segment is an
# HTML error page. Emitted as served, the same document would get a new URL
# every night, and council-alerts keys a meeting on its agenda URL, so every
# Barcoo meeting would be ingested afresh each night. The hash is replaced
# with 32 zeros, which keeps the served URL's shape and makes it stable.
_STABLE_HASH = "0" * 32
_DOWNLOAD = re.compile(r"^/download/(\d+)/[^/?#]*$")

_ROOTS = {
    "agenda": "ctl00$PlaceHolderContent$FolderBrowser$FolderList$ctrl0",
    "minutes": "ctl00$PlaceHolderContent$FolderBrowser$FolderList$ctrl1",
}
_POSTBACK = re.compile(r"__doPostBack\('([^']+)','([^']*)'\)")
_FILE_DATE = re.compile(r"^\s*(20\d\d)[\s-]+(\d{1,2})[\s-]+(\d{1,2})(?!\d)")
# Issued alongside the agenda, not the agenda itself.
_NOT_A_PAPER = re.compile(r"\blate\b|attachment|closed", re.IGNORECASE)


def _meeting_type(filename: str) -> str:
    lowered = filename.lower()
    if "post-election" in lowered or "post election" in lowered:
        return "Post-Election Meeting"
    if "special" in lowered:
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


def _file_date(match: re.Match) -> Optional[datetime.date]:
    year, month, day = (int(g) for g in match.groups())
    if month > 12 >= day:
        # "2022-14-12.pdf" is the minutes of 14 December 2022: day and month
        # typed the wrong way round, which only a month past 12 can show.
        month, day = day, month
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


# How far apart a lone agenda and lone minutes of one meeting type, in one
# month, can be dated and still be one meeting.
_MOVED_DAYS = 7


def _join_moved(meetings: dict[tuple, dict]) -> None:
    """Join an agenda-only and a minutes-only meeting a few days apart.

    The 19 April 2023 minutes are filed as "2023-04-18.pdf"; the agenda is
    "2023 04 19.pdf", and both PDFs say Wednesday 19 April. Joined only when
    each is the other's sole candidate, on the agenda's date: the agenda is
    named when it is issued for that day, the minutes' file name is typed
    later and is where the slips are.
    """

    def lone(kind: str) -> list[tuple]:
        return [key for key, papers in meetings.items() if set(papers) == {kind}]

    for minutes_key in lone("minutes"):
        date, name = minutes_key

        def near(key: tuple) -> bool:
            return (
                key[1] == name
                and (key[0].year, key[0].month) == (date.year, date.month)
                and abs((key[0] - date).days) <= _MOVED_DAYS
            )

        agenda_keys = [key for key in lone("agenda") if near(key)]
        rivals = [key for key in lone("minutes") if near(key)]
        if len(agenda_keys) == 1 and rivals == [minutes_key]:
            meetings[agenda_keys[0]]["minutes"] = meetings.pop(minutes_key)["minutes"]


@register_scraper
class BarcooScraper(BaseScraper):
    # Six requests, each a full WebForms page: about 11.5 s for one year.
    expected_seconds = 12.0

    def __init__(self):
        super().__init__("barcoo", "QLD", "https://www.barcoo.qld.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _postback(self, html: str, target: str, argument: str = "") -> str:
        """Submit the page's form as its own JavaScript would."""
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        for field in soup.find_all("input"):
            name = field.get("name")
            if not name or field.get("type") in ("image", "submit", "button"):
                continue
            data[name] = field.get("value", "")
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = argument
        return self.fetcher.fetch_with_requests(_PUBLICATIONS_URL, method="POST", data=data)

    @staticmethod
    def _folders(html: str, root: str) -> dict[str, str]:
        """``{folder path: postback argument}`` in one root's tree."""
        folders = {}
        for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            match = _POSTBACK.search(anchor["href"])
            if not match or match.group(1) != f"{root}$FolderTree":
                continue
            # The argument is a JavaScript string literal, so a subfolder's
            # path separator arrives doubled: 's2026\\Unconfirmed Minutes'.
            argument = match.group(2).replace("\\\\", "\\")
            if argument.startswith("s"):
                folders[argument[1:]] = argument
        return folders

    @staticmethod
    def _files(html: str) -> list[tuple[str, str]]:
        """(file name, URL) for each document the folder lists."""
        files = []
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.select(".documents-list a.document-name[href]"):
            match = _DOWNLOAD.match(anchor["href"])
            if match:
                url = f"{_PORTAL}/download/{match.group(1)}/{_STABLE_HASH}"
                files.append((anchor.get_text(" ", strip=True), url))
            elif anchor["href"].startswith("/download/"):
                raise ValueError(f"unexpected download link shape: {anchor['href']!r}")
        return files

    def _papers(self, html: str, kind: str, wanted: set[int]) -> tuple[str, list]:
        """Open one root and the wanted years in it.

        Returns the last page (the next postback needs its form state) and
        ``(file name, URL, unconfirmed)`` for every file found.

        A failed postback is left to raise. Each step needs the form state
        of the one before, so nothing after a failure can be read anyway,
        and in a one-year run a lost agenda folder would otherwise report
        every meeting without its agenda, and a lost "Unconfirmed Minutes"
        folder would quietly drop the newest minutes.
        """
        root = _ROOTS[kind]
        html = self._postback(html, f"{root}$ExpandFolders")
        folders = self._folders(html, root)
        found = []
        for path, argument in sorted(folders.items()):
            if not re.fullmatch(r"20\d\d", path) or int(path) not in wanted:
                continue
            html = self._postback(html, f"{root}$FolderTree", argument)
            found.extend((name, url, False) for name, url in self._files(html))
            unconfirmed = self._folders(html, root).get(f"{path}\\Unconfirmed Minutes")
            if kind == "minutes" and unconfirmed:
                html = self._postback(html, f"{root}$FolderTree", unconfirmed)
                found.extend((name, url, True) for name, url in self._files(html))
        return html, found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Every request is left to raise: an empty or short result would
        # report a broken portal as a council with fewer meetings.
        html = self.fetcher.fetch_with_requests(_PUBLICATIONS_URL)
        html, agendas = self._papers(html, "agenda", wanted)
        _, minutes = self._papers(html, "minutes", wanted)

        meetings: dict[tuple, dict[str, tuple[str, bool]]] = {}
        for kind, files in (("agenda", agendas), ("minutes", minutes)):
            for name, url, unconfirmed in files:
                if not name.lower().endswith(".pdf") or _NOT_A_PAPER.search(name):
                    continue
                match = _FILE_DATE.match(name)
                if not match:
                    self.logger.warning(f"{self.council_name}: cannot date {kind} {name!r}; skipped")
                    continue
                date = _file_date(match)
                if date is None:
                    self.logger.warning(f"{self.council_name}: bad date in {name!r}; skipped")
                    continue
                if date.year not in wanted:
                    continue
                papers = meetings.setdefault((date, _meeting_type(name)), {})
                current: Optional[tuple[str, bool]] = papers.get(kind)
                # Confirmed minutes (the year folder) over the unconfirmed
                # copy, which can linger after the move.
                if current is None or (current[1] and not unconfirmed):
                    papers[kind] = (url, unconfirmed)

        _join_moved(meetings)

        results = []
        for (date, name), papers in sorted(meetings.items()):
            agenda_url = papers["agenda"][0] if "agenda" in papers else None
            minutes_url = papers["minutes"][0] if "minutes" in papers else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_PUBLICATIONS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
