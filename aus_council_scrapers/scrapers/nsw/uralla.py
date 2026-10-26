import datetime
import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.opencities import OpenCitiesArchive

# The council's OpenCities meetings listing, which holds every meeting from
# 2014 until it moved to InfoCouncil, and overlaps it until December 2024.
ARCHIVE = (
    "https://www.uralla.nsw.gov.au/Your-Council/"
    "Council-meeting-agendas-and-minutes/Download-or-read-meeting-documents"
)

# The first meeting on InfoCouncil, the 2 November 2023 Extraordinary Council.
# From this day InfoCouncil's copy is used and the archive's is skipped.
INFOCOUNCIL_FROM = datetime.date(2023, 11, 2)


@register_scraper
class UrallaScraper(InfoCouncilScraper):
    # InfoCouncil holds Council meetings only, from November 2023. The
    # committee cell carries the venue and "Council Addendum" rows hold
    # supplementary agendas, so the tidy flag is on.
    #
    # Asking for a year the grid does not hold (2020–2022, 2027) returns the
    # current year's grid instead. Those rows are dated in the current year,
    # so the base class's check that each row's date is in the year asked for
    # already drops them. Meetings before INFOCOUNCIL_FROM come from the
    # OpenCities archive instead—see `scraper`.
    tidy_meeting_rows = True

    # Uralla's supplementary agendas are "Council Addendum" rows (file
    # `..._SUP.PDF`).
    SUPPLEMENTARY_NAME_REGEX = re.compile(
        r"\s*-?\s*\b(?:Supplementary|Late Items|Addendum)\b", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "uralla",
            "NSW",
            "https://www.uralla.nsw.gov.au",
            "https://uralla.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        results = super().scraper()

        # The archive is read only for the years before the move, so a
        # production run (the current year) never touches it.
        years_filter = getattr(self, "years_filter", None)
        wanted = (
            set(years_filter)
            if years_filter
            else set(range(EARLIEST_YEAR, clock.current_year() + 3))
        )
        archive_years = {y for y in wanted if y <= INFOCOUNCIL_FROM.year}
        if archive_years:
            results += _UrallaArchive(self, ARCHIVE, _archive_name).read(
                archive_years, before=INFOCOUNCIL_FROM
            )
        return results


class _UrallaArchive(OpenCitiesArchive):
    """Uralla files every paper in one flat Related Information list, so the
    link text is the main label. The shared link-text rules get three of its
    habits wrong, so the papers are picked here:

    * Until 2021 a meeting had an "Agenda" (an order of business, ~100 KB)
      *and* a "Business Paper" (the reports, MB), and in 2020 some had only
      the Business Paper. The Business Paper is the agenda worth storing,
      for the reason Resolve's packet is (see AGENTS.md).
    * "Minutes 26 July 2022 Business Agenda - CONFIRMED" is the minutes,
      but the shared rules see "Agenda" first and file it as one.
    * A few labels name only the meeting, so the filename is read instead.
    """

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        agendas: list[tuple[int, str]] = []
        minutes: list[str] = []
        for link in content.find_all("a", href=True):
            href = link["href"].strip()
            path = urllib.parse.urlparse(href).path
            if not path.lower().endswith(".pdf"):
                continue
            url = urllib.parse.urljoin(self.base_url, href)
            # Some labels are the filename: "Council-Minutes-26-September-...".
            label = link.get_text(" ", strip=True)
            kind = _classify(label)
            if kind is None:
                # And some say only which meeting it is: the 1 February 2022
                # Extraordinary Meeting's agenda is labelled "Extraordinary
                # Meeting 1 February 2022". Its filename,
                # business-paper-extraordinary-meeting-1-february-2022.pdf,
                # still says what it is. Only a silent label falls back: one
                # the label already rules out ("Tabled ...") stays out.
                kind = _classify(path.rsplit("/", 1)[-1][: -len(".pdf")])
            if kind == "minutes":
                minutes.append(url)
            elif isinstance(kind, int):
                agendas.append((kind, url))
        papers = {}
        if agendas:
            # Stable sort: the first listed wins among equals.
            papers["agenda"] = sorted(agendas, key=lambda a: a[0])[0][1]
        if minutes and minutes[0] != papers.get("agenda"):
            papers["minutes"] = minutes[0]
        return papers


def _classify(text: str) -> str | int | None:
    """ "minutes", an agenda's rank (0 is the full Business Paper, 1 an order
    of business), "other" for a file that is neither, or None when the text
    does not say."""
    text = re.sub(r"[-_]+", " ", text)
    if _NOT_A_PAPER.search(text):
        return "other"
    if re.match(r"^(?:Council\s+)?Minutes\b", text, re.IGNORECASE):
        return "minutes"
    if re.search(r"\bBusiness\s+Papers?\b", text, re.IGNORECASE):
        # "Business Paper 27 October 2020" is the full paper; "Agenda
        # Business Paper 15 December 2020" is the 97 KB order of business
        # beside it, so it ranks with the plain agendas.
        return 1 if re.match(r"^Agenda\b", text, re.IGNORECASE) else 0
    if re.search(r"\bAgenda\b", text, re.IGNORECASE):
        return 1
    return None


# Files in the same list that are neither the agenda nor the minutes: late
# reports and items, attachment books, requests for an extraordinary meeting,
# papers tabled or reissued at the meeting, the mayoral minute, and other
# bodies' draft minutes ("Draft UTEC Minutes").
_NOT_A_PAPER = re.compile(
    r"\b(?:late|attachments?|supplement\w*|request|reissued|tabled|"
    r"replacement|amendments|mayoral|separate\s+cover|draft|register|urgent)\b",
    re.IGNORECASE,
)


def _archive_name(meeting_type: str, title: str) -> str:
    # The archive's types are "Ordinary Meeting", "Extraordinary Meeting" and
    # "Special Meeting"; named here as InfoCouncil names them, so a meeting
    # type reads the same across the move. InfoCouncil has no special type.
    if re.search(r"extra", meeting_type, re.IGNORECASE):
        return "Extraordinary Council"
    if re.search(r"special", meeting_type, re.IGNORECASE):
        return "Special Council"
    return "Council"
