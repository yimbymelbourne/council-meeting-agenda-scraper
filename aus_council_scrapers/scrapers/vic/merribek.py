import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import (
    BaseScraper,
    ScraperReturn,
    register_scraper,
)

_BASE_URL = "https://www.merri-bek.vic.gov.au"
_LISTING_URL = (
    "https://www.merri-bek.vic.gov.au/my-council/council-and-committee-meetings"
    "/council-meetings/council-meeting-minutes/"
)

# The listing nests one accordion per year; inside each, an <h3> gives the
# meeting date and the <ul>s that follow it hold that meeting's documents,
# until the next <h3> starts the next meeting. Grouping by heading is what
# keeps two meetings held on one date - a Special Council meeting and an
# ordinary one - from collapsing into a single record.
_ACCORDION_SELECTOR = "li.accordion-item"
_CONTENT_CLASS = "accordion-item__content"

# Trailing format/size annotation on a link: "(PDF 12Mb)", "(DOC)", "(DOCX 2Mb)".
_FORMAT_NOTE_RE = re.compile(r"\((?:PDF|DOCX?|XLSX?)\b[^)]*\)", re.IGNORECASE)

# A document link says which document it is, and everything before that word is
# the council's own name for the meeting ("Special Council Agenda 20 July 2026").
_DOC_KIND_RE = re.compile(r"\b(agenda|minutes)\b", re.IGNORECASE)
_MINUTES_RE = re.compile(r"\bminutes\b", re.IGNORECASE)

# Bundles of attachments are published alongside the agenda under a name that
# still says "agenda". They are not the agenda, and picking one up as the
# agenda means the keyword scan reads appendices instead of the meeting items.
_ATTACHMENT_BUNDLE_RE = re.compile(
    r"attachments?\s+only|separately\s+circulated|under\s+separate\s+cover",
    re.IGNORECASE,
)

# Most meetings publish the agenda twice: the items on their own, and the same
# items with every attachment appended (often 20-30Mb). The former is the
# agenda proper, so prefer it when both exist.
_NO_ATTACHMENTS_RE = re.compile(r"\b(?:without|no)\s+attachments\b", re.IGNORECASE)

_MEETING_WORD_RE = re.compile(r"\bmeeting\b", re.IGNORECASE)
_NAMES_A_MEETING_RE = re.compile(r"\b(?:meeting|election)\b", re.IGNORECASE)
_ENDS_WITH_COUNCIL_RE = re.compile(r"\bcouncil$", re.IGNORECASE)

_DEFAULT_NAME = "Council Meeting"

# The (url, label) pair `_pick_documents` would have returned had the meeting
# published this kind of document.
_NO_DOCUMENT = (None, "")


def _clean(text: str) -> str:
    """Collapse the non-breaking spaces and runs of padding the CMS emits."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


@register_scraper
class MerribekScraper(BaseScraper):
    def __init__(self):
        super().__init__("merri_bek", "VIC", _BASE_URL)

    def _meeting_groups(self, soup: BeautifulSoup) -> list[tuple[str, list]]:
        """Split the listing into (heading, links) pairs, one per meeting."""
        groups: list[tuple[str, list]] = []
        for accordion in soup.select(_ACCORDION_SELECTOR):
            content = accordion.find(class_=_CONTENT_CLASS)
            if not content:
                continue
            links: list = []
            for element in content.children:
                if getattr(element, "name", None) is None:
                    continue
                if element.name == "h3":
                    links = []
                    groups.append((element.get_text(" ", strip=True), links))
                elif groups:
                    links.extend(element.find_all("a", href=True))
        return groups

    def _pick_documents(self, links: list) -> dict[str, tuple[str, str]]:
        """Choose one agenda and one minutes PDF from a meeting's links.

        Returns `{kind: (url, label)}` where `label` is the link text with its
        format annotation removed, which is where the meeting name comes from
        when the heading is only a date.
        """
        best: dict[str, tuple[tuple, str, str]] = {}
        for link in links:
            href = link["href"]
            label = _clean(_FORMAT_NOTE_RE.sub("", link.get_text(" ", strip=True)))

            kind_match = _DOC_KIND_RE.search(label)
            if not kind_match:
                # Livestream recordings and one-off item attachments, neither of
                # which is the meeting's agenda or minutes.
                continue
            if _ATTACHMENT_BUNDLE_RE.search(label) or _ATTACHMENT_BUNDLE_RE.search(
                href
            ):
                continue
            if not href.split("?")[0].lower().endswith(".pdf"):
                # The council also publishes Word versions, and for meetings
                # before 2019 that is all it published. Only a PDF is any use
                # downstream, so a Word-only meeting is left out entirely.
                continue

            kind = "minutes" if _MINUTES_RE.search(label) else "agenda"
            rank = (bool(_NO_ATTACHMENTS_RE.search(label)),)
            if kind not in best or rank > best[kind][0]:
                best[kind] = (
                    rank,
                    urllib.parse.urljoin(_LISTING_URL, href),
                    _clean(label[: kind_match.start()]),
                )

        return {kind: (url, label) for kind, (_, url, label) in best.items()}

    def _meeting_name(self, heading: str, documents: dict) -> str:
        """Name the meeting from its heading, falling back to its documents.

        Headings are usually just the date, but the council qualifies the ones
        that are not ordinary Council meetings ("27 March 2023 - Special
        Council Meeting", "29 November 2022 - Mayoral Election"). Where the
        heading says nothing, the document labels do: "Special Council Agenda
        20 July 2026" sits under a heading of "20 July 2026".
        """
        qualifier = _clean(self.date_regex.sub("", heading)).strip(" -–—()|,")
        _, agenda_label = documents.get("agenda", _NO_DOCUMENT)
        _, minutes_label = documents.get("minutes", _NO_DOCUMENT)

        for candidate in (qualifier, agenda_label, minutes_label):
            if not candidate:
                continue
            if _NAMES_A_MEETING_RE.search(candidate):
                # "Council meeting" and "Ceremonial Meeting" already name one;
                # only the capitalisation needs settling.
                return _MEETING_WORD_RE.sub("Meeting", candidate)
            if _ENDS_WITH_COUNCIL_RE.search(candidate):
                # "Council", "Special Council" - the body, not the meeting.
                return f"{candidate} Meeting"
            # A bare qualifier such as "Special" or "(Special)" modifies the
            # ordinary name rather than replacing it.
            return f"{candidate} {_DEFAULT_NAME}"

        return _DEFAULT_NAME

    def scraper(self) -> list[ScraperReturn]:
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )

        results = []
        seen = set()
        for heading, links in self._meeting_groups(soup):
            date_match = self.date_regex.search(_clean(heading))
            if not date_match:
                continue

            documents = self._pick_documents(links)
            agenda_url, _ = documents.get("agenda", _NO_DOCUMENT)
            minutes_url, _ = documents.get("minutes", _NO_DOCUMENT)
            if not agenda_url and not minutes_url:
                continue

            name = self._meeting_name(heading, documents)
            date = _clean(date_match.group())

            # A handful of meetings are listed under two identical headings
            # pointing at the same documents - 14 June 2016 appears twice. Two
            # meetings on one date are real and kept; the same meeting listed
            # twice is not.
            identity = (name, date, agenda_url, minutes_url)
            if identity in seen:
                continue
            seen.add(identity)

            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    # The deprecated field is read as the agenda downstream, so
                    # it stays empty on a meeting that only published minutes.
                    download_url=agenda_url,
                )
            )

        self.logger.info(f"Found {len(results)} meetings")
        # The listing is ordered newest first, within a year and across years,
        # and that order is kept: callers that take the first result want the
        # most recent meeting.
        return results


if __name__ == "__main__":
    scraper = MerribekScraper()
    for result in scraper.scraper():
        print(result)
