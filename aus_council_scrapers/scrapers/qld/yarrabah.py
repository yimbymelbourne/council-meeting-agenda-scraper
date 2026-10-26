import datetime
import re
from typing import NamedTuple, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.yarrabah.qld.gov.au"
_LISTING_URL = f"{_BASE_URL}/council-meetings-agendas-minutes/"

# Yarrabah Aboriginal Shire Council keeps its whole history, 2013 on, on one
# WordPress page: a heading per year, then one link per paper, each labelled
# by hand with date, meeting and paper—
#
#   "16 September 2026- Ordinary Council Meeting - Minutes (Unconfirmed)"
#   "27 April 2026 – Trustee Meeting – Agenda"
#   "25 October 2022 – Ordinary Council Meeting Minutes"
#
# —with the dashes as hyphens, en dashes or missing. Papers are grouped into
# meetings by the label's date and meeting name. Trustee meetings (the
# council sitting as trustee of the Deed of Grant in Trust land) are kept
# with council meetings: they are on the same page and decide land matters.
#
# The labels are typed by hand and some point at the wrong file, so each
# link is checked against its filename. Filenames date papers as YYYYMMDD
# (CO_20260318_MIN_2370), DDMMYYYY (Trustee-Meeting-Agenda_Web-27042026) or
# in words (…-Wednesday-18-February-2026). Fourteen-digit scan stamps are not
# dates and are not read. Where the two disagree, the cover decides which is
# wrong, and the covers checked follow these patterns:
#
# - The filename names the other paper but the same date: the label is wrong
#   about the paper. "29 June 2026 – Ordinary Council Meeting – Agenda" links
#   …-29-June-2026-Minutes-1.pdf, whose cover is that meeting's minutes, so it
#   is filed as minutes.
# - The filename's date is another meeting on the page: the label is wrong
#   about the meeting. "21 May 2021 – Minutes" links 20210526-Minutes, the
#   26 May minutes (cover read), so it moves to 26 May. "28 January 2026 –
#   Minutes" links the 18 February minutes; 18 February already has its own,
#   so 28 January is left with its agenda.
# - The filename's date is within a fortnight, on no other meeting, and every
#   paper in the label agrees on it: the label's day is wrong. Both "23 May
#   2023" papers are filed 20230517 and the cover reads 17 May 2023, so the
#   meeting is dated 17 May.
# - Otherwise the filename is the typo. "20 May 2026 – Agenda" links
#   Council-Meeting_20022026.pdf, whose cover reads 20 May 2026; 20 February
#   is no meeting, so the label's date stands.
#
# A filename naming only another month ("…_November-2025") is still left out:
# with no day there is nothing to move it to.
# Some papers are Word documents (.docx); only PDFs are kept.
_MONTH_NAMES = [datetime.date(2000, m, 1).strftime("%B").lower() for m in range(1, 13)]
_MONTH_ABBR = {name[:3]: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTHS = {**{n: i for i, n in enumerate(_MONTH_NAMES, start=1)}, **_MONTH_ABBR, "sept": 9}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))

_LABEL = re.compile(rf"^\s*(\d{{1,2}})\s+({_MONTH})[a-z]*\s+(\d{{4}})\b(.*)$", re.IGNORECASE)
_PAPER = re.compile(r"[\s\-–—]*(agenda|minutes)\b(.*)$", re.IGNORECASE)
_SEPARATORS = " -–— "

_WORD_DATE = re.compile(rf"\b(\d{{1,2}}) ({_MONTH})\b (\d{{4}})\b")
_EIGHT_DIGITS = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_MONTH_WORD = re.compile(rf"\b({'|'.join(_MONTH_NAMES)})\b")


def _filename_words(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1]).lower()
    name = re.sub(r"\.pdf$", "", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _eight_digit_date(digits: str) -> Optional[datetime.date]:
    for fmt in ("%Y%m%d", "%d%m%Y"):
        try:
            parsed = datetime.datetime.strptime(digits, fmt).date()
        except ValueError:
            continue
        if 2000 <= parsed.year <= 2100:
            return parsed
    return None


def _filename_date(words: str) -> Optional[datetime.date]:
    match = _WORD_DATE.search(words)
    if match:
        try:
            return datetime.date(int(match[3]), _MONTHS[match[2]], int(match[1]))
        except ValueError:
            return None
    for digits in _EIGHT_DIGITS.findall(words.replace(" ", "_")):
        parsed = _eight_digit_date(digits)
        if parsed:
            return parsed
    return None


def _meeting_name(text: str) -> str:
    name = re.sub(r"\s+", " ", text.strip(_SEPARATORS))
    # "Ordinary Council meeting" on one label, "Ordinary Council Meeting" on
    # the rest.
    return " ".join(w if w.isupper() else w[0].upper() + w[1:] for w in name.split())


@register_scraper
class YarrabahScraper(BaseScraper):
    def __init__(self):
        super().__init__("yarrabah", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")

        # First pass: every dated paper link on the page, in page order. The
        # whole page is read, not just the wanted years, because a mislabelled
        # paper is placed by the other meetings listed (see the header).
        papers: list[_Paper] = []
        labelled = 0
        for link in soup.find_all("a", href=True):
            url = urljoin(_LISTING_URL, link["href"].strip())
            if "/wp-content/uploads/" not in urlparse(url).path:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            match = _LABEL.match(label)
            if not match:
                continue
            labelled += 1
            day, month_word, year, rest = match.groups()
            try:
                label_date = datetime.date(int(year), _MONTHS[month_word.lower()[:3]], int(day))
            except (ValueError, KeyError):
                self.logger.warning(f"{self.council_name}: unreadable date in {label!r}")
                continue
            paper = _PAPER.search(rest)
            if not paper:
                # "12 April 2018 – Housing & Homelessness Strategy"
                continue
            if "attachment" in paper[2].lower():
                continue
            name = _meeting_name(rest[: paper.start()])
            if not name or not urlparse(url).path.lower().endswith(".pdf"):
                continue
            papers.append(_Paper(label, url, label_date, name, paper[1].lower()))

        if not labelled:
            raise RuntimeError(f"{self.council_name}: no dated paper links at {_LISTING_URL}")

        listed = {(p.label_date, p.name) for p in papers}
        by_label: dict[tuple[datetime.date, str], list[_Paper]] = {}
        for p in papers:
            by_label.setdefault((p.label_date, p.name), []).append(p)

        meetings: dict[tuple[datetime.date, str], dict[str, str]] = {}
        order: list[tuple[datetime.date, str]] = []
        special: set[tuple[datetime.date, str]] = set()
        for p in papers:
            # A paper moves at most a few weeks (see _place), so papers more
            # than a year from every wanted year are not checked or warned on.
            if not wanted & {p.label_date.year - 1, p.label_date.year, p.label_date.year + 1}:
                continue
            placed = self._place(p, listed, by_label[(p.label_date, p.name)])
            if placed is None:
                continue
            meeting_date, kind = placed
            if meeting_date.year not in wanted:
                continue
            key = (meeting_date, p.name)
            if key not in meetings:
                meetings[key] = {}
                order.append(key)
            if kind in meetings[key]:
                if meetings[key][kind] != p.url:
                    self.logger.warning(
                        f"{self.council_name}: {p.label!r} links {p.url}, a second "
                        f"{kind} for {meeting_date}; the first listed is kept"
                    )
                continue
            meetings[key][kind] = p.url
            if "extra" in _filename_words(p.url).split():
                special.add(key)

        results = []
        for key in order:
            meeting_date, name = key
            found = meetings[key]
            # InfoCouncil marks a special meeting's papers _EXTRA
            # (CO_20201113_MIN_2202_EXTRA_SAVED.pdf). The 2020 labels call
            # all of them Ordinary; from 2021 the labels say Special.
            if name == "Ordinary Council Meeting" and key in special:
                name = "Special Council Meeting"
            agenda_url = found.get("agenda")
            minutes_url = found.get("minutes")
            results.append(
                ScraperReturn(
                    name=name,
                    date=meeting_date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name}: no papers for {sorted(wanted)} at {_LISTING_URL}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _place(
        self,
        p: "_Paper",
        listed: set[tuple[datetime.date, str]],
        siblings: list["_Paper"],
    ) -> Optional[tuple[datetime.date, str]]:
        """The meeting date and paper kind a link belongs to, or None to leave
        it out. The rules, and the covers behind them, are in the header."""
        words = _filename_words(p.url)
        tokens = set(words.split())
        is_minutes = "minutes" in tokens or "min" in tokens
        is_agenda = "agenda" in tokens or "agn" in tokens
        kind = p.kind
        if is_minutes != is_agenda:
            kind = "minutes" if is_minutes else "agenda"

        named = _filename_date(words)
        if named is None:
            month = _MONTH_WORD.search(words)
            if month and _MONTHS[month[1]] != p.label_date.month:
                self._warn(p, f"names {month[1]}; left out")
                return None
            date = p.label_date
        elif named == p.label_date:
            date = p.label_date
        elif (named, p.name) in listed:
            self._warn(p, f"is dated {named}, another meeting listed; filed there")
            date = named
        elif abs((named - p.label_date).days) <= 14 and all(
            _filename_date(_filename_words(s.url)) == named for s in siblings
        ):
            self._warn(p, f"is dated {named}, as are all its meeting's papers; dated {named}")
            date = named
        else:
            self._warn(p, f"is dated {named}, which is no meeting; the label's date is kept")
            date = p.label_date

        if kind != p.kind:
            self._warn(p, f"is the {kind}, not the {p.kind}; filed as {kind}")
        return date, kind

    def _warn(self, p: "_Paper", what: str) -> None:
        self.logger.warning(f"{self.council_name}: {p.label!r} links {p.url}, which {what}")


class _Paper(NamedTuple):
    label: str
    url: str
    label_date: datetime.date
    name: str
    kind: str
