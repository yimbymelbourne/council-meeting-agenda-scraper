"""Brisbane City Council: Council and planning committee meetings.

Brisbane publishes in two places, and neither holds everything.

**Minutes** are on the council's meetings page, one 2 MB static page with
every minutes link back to 2020: full Council under `<year> meeting minutes`
headings, then a section per standing committee with `<year> minutes`
sub-headings. That page is the source for minutes.

**Agendas** are not on it. The council's pages have only ever linked the
current week's agendas: a Wayback capture of its former "Council and Committee
meeting documents" page (3 December 2024) links that week's Council agenda
into the bucket below, and today's page has an "Upcoming committee and Council
meetings" section that holds only the resumption date while Council is in
recess. Once a meeting has passed its agenda link goes, and only the minutes
stay. Past agendas survive in the Amazon S3 bucket that every document link
on the page points into, `docs.brisbane.qld.gov.au`, which is publicly
listable. So agendas come from **listing that bucket**. That is a step past
reading a page the council wrote: it enumerates files the council uploaded
and once linked, rather than following its current links. It is also the
only route to them, and the listing is public by the council's own
configuration. If the council closes it, this scraper keeps working from the
minutes alone and warns that the agendas are missing.

Three consequences of the data, not of the scraper:

- Brisbane published agendas and minutes as Word documents (.docx, some
  .doc) until mid-2025. Only PDFs go in agenda_url/minutes_url, so a meeting
  whose papers are all Word documents has nothing to emit and is skipped;
  where one paper is a PDF, the meeting is kept with just that one.
- Folder names in the bucket drift ("09 -Sep", "08 - Aug", "12-Dec") and
  documents are often filed under the following week's folder—a minutes
  file for 9 June sits under "16 June 2026". The filename's own date is
  reliable where the folder is not, so dates are read from the filename and
  the folder is only a fallback for the few filenames without one.
- A listed file is not always a readable one. A few objects are private and
  answer 403, and nothing in the listing says which. The ones seen are all
  stray PDFs from the Word era (16 February 2021's agenda is one), so agendas
  dated before mid-2025 are checked with a one-byte ranged GET and dropped if
  refused. That is about seven requests across the whole history and none
  for a year since 2026; checking the PDF era too would cost a request per
  meeting for no failures seen.

Scope: full Council meetings plus the planning committee. Brisbane runs nine
standing committees, most meeting weekly. The City Planning, Suburban Renewal
and Economic Development Committee is the planning one: it keeps City Plan
current, oversees development assessment, decides delegated applications
during recess and recommends major project applications to Council. Council
adopts each committee's report at its next meeting, so its own minutes carry
the other committees' decisions.
"""

import re
import urllib.parse
from typing import Optional
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_MEETINGS_URL = (
    "https://www.brisbane.qld.gov.au/about-council/governance-and-strategy/"
    "council-and-standing-committee-meetings"
)
_BUCKET_URL = "https://s3.ap-southeast-2.amazonaws.com/docs.brisbane.qld.gov.au"
_BUCKET_ROOT = "Council and Committees/"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# The page says so: "All meetings are held at Brisbane City Hall, 64 Adelaide
# Street, Brisbane."
_LOCATION = "Brisbane City Hall, 64 Adelaide Street, Brisbane"

_COUNCIL = "council"
_PLANNING = "planning"

# The committee's heading on the page, which files every year's minutes under
# its current name.
_PLANNING_COMMITTEE = (
    "City Planning, Suburban Renewal and Economic Development Committee"
)

# Agenda filenames start with the committee's abbreviation. The planning
# committee has been renamed twice: CP&ED (to 2021), CP&SR (to mid-2025), then
# CPSR&ED, sometimes typed CPSRED or CPSR. Every other abbreviation (CA, C&A,
# CS, EP&S, F&CG, Infra, PT, Transport, CE, E&C, ...) is a committee outside
# scope.
_PLANNING_PREFIX = re.compile(r"^(?:CPSR&?ED|CPSR|CP&SR|CP&ED)\b", re.IGNORECASE)
_OTHER_COMMITTEE_PREFIX = re.compile(r"^[A-Z][A-Za-z&]*(?:&[A-Za-z]+)*\s-\s")
# Uploaded beside the agendas, and never the agenda itself.
_NOT_AN_AGENDA = re.compile(r"attachment|supplementary|minutes", re.IGNORECASE)
_VERSION = re.compile(r"\bv\s?(\d+)\b", re.IGNORECASE)
# The clerical copies ("GCCS - CCLO - Council - Agenda ...") and drafts sit
# beside the published agenda and are not always the same document: for 16
# September 2025 the GCCS-CCLO copy is three pages and leaves out a report the
# plain four-page one lists.
_CLERICAL = re.compile(r"^(?:GCCS|CCLO)\b|\bdraft\b", re.IGNORECASE)
# Before this date Brisbane published Word documents and the PDFs in the
# bucket are strays, some of them private. See the module docstring.
_PDF_ERA = "2025-07-01"
# "1 Sep 2026", "18 August 2026", and the slugged "19_aug_2025".
_FILENAME_DATE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_IN_PREFIX = re.compile(r"\b(20\d{2})\b")

# Page links that sit in the minutes tables but are not minutes.
_NOT_MINUTES = re.compile(r"tabled|presented|presentation|attachment", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
_COUNCIL_YEAR_HEADING = re.compile(r"^(\d{4}) meeting minutes$", re.IGNORECASE)


def _is_pdf(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith(".pdf")


def _council_meeting_name(texts: list[str]) -> str:
    """Name a full Council meeting from whatever its documents call it.

    "Post Recess" is the first ordinary meeting after a recess, not a kind of
    its own. The 25 June 2026 meeting is "Special (Post Budget)"—special
    wins over budget for the same reason.
    """
    joined = " ".join(texts).lower()
    if "special" in joined:
        return "Special Council Meeting"
    if "budget" in joined:
        return "Budget Council Meeting"
    if "post election" in joined or "post-election" in joined:
        return "Post-Election Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class BrisbaneScraper(BaseScraper):
    def __init__(self):
        super().__init__("brisbane", "QLD", "https://www.brisbane.qld.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    # --- minutes, from the council's page --------------------------------

    def _minutes(self, wanted: set[int]) -> Optional[dict[tuple, dict]]:
        """{(body, date): {"url", "label"}} for every minutes link in range,
        or None if the page could not be read."""
        try:
            html = self.fetcher.fetch_with_requests(_MEETINGS_URL)
        except Exception as e:
            self.logger.warning(f"brisbane: could not read the meetings page: {e}")
            return None

        soup = BeautifulSoup(html, "html.parser")
        start = soup.find(
            lambda tag: tag.name == "h2"
            and "meeting minutes and documents" in tag.get_text(" ").lower()
        )
        if start is None:
            self.logger.warning(
                "brisbane: the meetings page has no 'Meeting minutes and "
                "documents' section; its layout has changed"
            )
            return None

        found: dict[tuple, dict] = {}
        body = None
        skipped_word = 0

        # Walk the section in document order. An h3 names what follows: a
        # Council year, or a committee. The year sub-headings under each
        # committee are not needed, since every link carries its own date.
        # The section ends at the next h2.
        for element in start.find_all_next(["h2", "h3", "a"]):
            if element.name == "h2":
                break
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if element.name == "h3":
                if _COUNCIL_YEAR_HEADING.match(text):
                    body = _COUNCIL
                elif text == _PLANNING_COMMITTEE:
                    body = _PLANNING
                else:
                    body = None
                continue

            if body is None or not element.get("href"):
                continue
            if not _MINUTES_LABEL.search(text) or _NOT_MINUTES.search(text):
                continue

            date_match = self.date_regex.search(text)
            if not date_match:
                continue
            date = parse_date(date_match.group(), dayfirst=True).date()
            if date.year not in wanted:
                continue

            url = self._absolute(element["href"])
            if not _is_pdf(url):
                skipped_word += 1
                continue
            found.setdefault((body, date.isoformat()), {"url": url, "label": text})

        if skipped_word:
            self.logger.info(
                f"brisbane: {skipped_word} minutes in range are Word documents, "
                f"not PDFs, and were not linked"
            )
        return found

    @staticmethod
    def _absolute(href: str) -> str:
        # The page mixes three forms for the same bucket: the S3 path URL,
        # the docs.brisbane.qld.gov.au alias, and protocol-relative links with
        # raw spaces in them.
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        href = urllib.parse.urljoin(_MEETINGS_URL, href)
        return urllib.parse.quote(href, safe=":/?&=%+#")

    # --- agendas, from the bucket ----------------------------------------

    def _list(self, **params) -> Optional[list[ElementTree.Element]]:
        """Every page of one ListObjectsV2 query, or None if it failed."""
        pages = []
        token = None
        while True:
            query = {"list-type": "2", **params}
            if token:
                query["continuation-token"] = token
            url = f"{_BUCKET_URL}?{urllib.parse.urlencode(query)}"
            try:
                listing = ElementTree.fromstring(self.fetcher.fetch_with_requests(url))
            except Exception as e:
                self.logger.warning(
                    f"brisbane: could not list the document bucket "
                    f"({params.get('prefix')!r}); agendas will be missing: {e}"
                )
                return None
            pages.append(listing)
            if listing.findtext(f"{_S3_NS}IsTruncated") != "true":
                return pages
            token = listing.findtext(f"{_S3_NS}NextContinuationToken")

    def _year_prefixes(self, wanted: set[int]) -> Optional[list[str]]:
        """The bucket folders holding the wanted years.

        Mostly "<year>/", but late 2020 was filed in date-named folders at the
        top level ("24 November 2020/"), so the folders are discovered rather
        than assumed.
        """
        pages = self._list(prefix=_BUCKET_ROOT, delimiter="/")
        if pages is None:
            return None
        prefixes = []
        for page in pages:
            for common in page.iter(f"{_S3_NS}CommonPrefixes"):
                prefix = common.findtext(f"{_S3_NS}Prefix") or ""
                year = _YEAR_IN_PREFIX.search(prefix[len(_BUCKET_ROOT) :])
                if year and int(year.group(1)) in wanted:
                    prefixes.append(prefix)
        return sorted(prefixes)

    @staticmethod
    def _agenda_body(name: str) -> Optional[str]:
        # Some files carry an index prefix ("01 - P&AT - Agenda ...").
        name = re.sub(r"^\d+\s-\s", "", name)
        if _PLANNING_PREFIX.match(name):
            return _PLANNING
        if re.match(r"^(?:agenda|council)\b", name, re.IGNORECASE):
            return _COUNCIL
        if _OTHER_COMMITTEE_PREFIX.match(name):
            # Another committee—unless a clerical prefix ("GCCS - CCLO -
            # Council - Agenda - Ordinary") hides a Council agenda behind it.
            # Only the word "Council" counts: a committee can hold a special
            # meeting too.
            return _COUNCIL if re.search(r"\bcouncil\b", name, re.I) else None
        return None

    def _agendas(self, wanted: set[int]) -> Optional[dict[tuple, dict]]:
        """{(body, date): {"url", "label"}}, one agenda PDF per meeting, or
        None if the bucket could not be listed.

        A meeting often has several: "Agenda - Ordinary - 17 Feb 2026.pdf"
        uploaded beforehand and "... v2.pdf" on the day. The latest version is
        the agenda the meeting actually ran to, so it wins. Within a version
        the plain copy beats a clerical one or a draft, then the larger file
        (a later agenda adds items, never removes them), then the later
        upload. LastModified comes last because it means little: the council
        bulk re-uploads folders, so two copies often differ by seconds.
        """
        candidates: dict[tuple, list[tuple]] = {}

        prefixes = self._year_prefixes(wanted)
        if prefixes is None:
            return None
        for prefix in prefixes:
            pages = self._list(prefix=prefix)
            for page in pages or []:
                for item in page.iter(f"{_S3_NS}Contents"):
                    key = item.findtext(f"{_S3_NS}Key") or ""
                    filename = key.rsplit("/", 1)[-1]
                    if not filename.lower().endswith(".pdf"):
                        continue
                    # Slugged uploads ("agenda_-_ordinary_-_19_aug_2025_v3")
                    # read the same once their separators are spaces.
                    stem = re.sub(r"[_\s]+", " ", filename[: -len(".pdf")])
                    stem = re.sub(r"(?<=\w)-(?=\w)", " ", stem)
                    if not re.search(r"\bagenda\b", stem, re.IGNORECASE):
                        continue
                    if _NOT_AN_AGENDA.search(stem):
                        continue
                    body = self._agenda_body(stem)
                    if body is None:
                        continue

                    date = self._agenda_date(stem, key)
                    if date is None or date.year not in wanted:
                        continue

                    version = _VERSION.search(stem)
                    rank = (
                        int(version.group(1)) if version else 1,
                        not _CLERICAL.search(stem),
                        int(item.findtext(f"{_S3_NS}Size") or 0),
                        item.findtext(f"{_S3_NS}LastModified") or "",
                        -len(filename),
                    )
                    url = f"{_BUCKET_URL}/{urllib.parse.quote(key)}"
                    candidates.setdefault((body, date.isoformat()), []).append(
                        (rank, {"url": url, "label": stem})
                    )

        agendas = {}
        for meeting, found in sorted(candidates.items()):
            # Best first, so a private copy can give way to the next one.
            for _, agenda in sorted(found, key=lambda pair: pair[0], reverse=True):
                if meeting[1] >= _PDF_ERA or self._readable(agenda["url"]):
                    agendas[meeting] = agenda
                    break
        return agendas

    def _readable(self, url: str) -> bool:
        """Whether a listed object is public. One byte, not the whole PDF."""
        try:
            self.fetcher.fetch_with_requests(url, headers={"Range": "bytes=0-0"})
            return True
        except Exception as e:
            self.logger.warning(
                f"brisbane: the bucket lists {url} but will not serve it; "
                f"dropping it: {e}"
            )
            return False

    @staticmethod
    def _agenda_date(stem: str, key: str):
        match = _FILENAME_DATE.search(stem)
        if match is None:
            # "Council - Budget - 2026 - Agenda.pdf": only its folder,
            # "17 June 2026", says which day.
            for folder in reversed(key.split("/")[:-1]):
                match = _FILENAME_DATE.search(folder)
                if match:
                    break
        if match is None:
            return None
        try:
            return parse_date(" ".join(match.groups()), dayfirst=True).date()
        except (ValueError, OverflowError):
            return None

    # --- the meetings -----------------------------------------------------

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        minutes = self._minutes(wanted)
        agendas = self._agendas(wanted)
        if minutes is None and agendas is None:
            # Both sources failed. An empty list would read downstream as "no
            # meetings", not "scraper broken".
            raise RuntimeError(
                "brisbane: neither the meetings page nor the document bucket "
                "could be read"
            )
        minutes = minutes or {}
        agendas = agendas or {}

        results = []
        # Council and the committee meet on the same Tuesdays; sorting on the
        # whole (date, body) key keeps the order stable between runs.
        for body, date in sorted(
            set(minutes) | set(agendas), key=lambda m: (m[1], m[0])
        ):
            agenda = agendas.get((body, date))
            minute = minutes.get((body, date))
            agenda_url = agenda["url"] if agenda else None
            minutes_url = minute["url"] if minute else None

            if body == _COUNCIL:
                name = _council_meeting_name(
                    [doc["label"] for doc in (agenda, minute) if doc]
                )
            else:
                name = _PLANNING_COMMITTEE

            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    # Every paper prints a start time, but neither source
                    # carries one, and it is not fixed enough to default:
                    # ordinary Council was 2pm in 2020-21 and 1pm since 2022,
                    # 4 November 2025 sat at 2.30pm, budget meetings at 11am,
                    # the 26 June 2025 special at 6.20pm; the planning
                    # committee moved from 10am (2021) to 8.30am. Reading it
                    # would cost a PDF download per meeting.
                    time=None,
                    webpage_url=_MEETINGS_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=_LOCATION,
                )
            )

        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
