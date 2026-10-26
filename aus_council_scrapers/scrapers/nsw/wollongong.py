import json
import re
import urllib.parse
from datetime import date, datetime

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wollongong.nsw.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings/council-business-papers"

# A documented robots.txt exception, the second after `swan`. Wollongong's
# business papers are a Squiz Funnelback collection. The listing page above
# is allowed, but bare it shows only the newest 50 documents (two or three
# meetings), and every route to the rest is disallowed (checked 26 Oct 2026):
#
#   www.wollongong.nsw.gov.au/robots.txt, the page's own pager and filters:
#       Disallow: *?*query=
#       Disallow: *?*collection=
#   wolcc-search.funnelback.squiz.cloud/robots.txt, the search API itself:
#       Disallow: /search/
#       Disallow: /s/
#
# The 2016-2024 "archive" pages on www are the same collection: bare, each
# shows the newest 50 of its year's 200-330 documents, which are mostly
# per-item PDFs, and its pager is the same disallowed parameters. This
# scraper reads the API under `/s/`, `/s/search.json`, because the
# maintainer asked for Wollongong on 26 Oct 2026 ("We gotta get Wollongong
# for sure"), no allowed route lists a whole year, and these are the
# council's official public record. The load is one request per year (one a
# night in production), with the per-item rows excluded on the server so a
# year is about 110 KB. Nothing else on either host is requested: the
# document URLs come straight from the results, not through Funnelback's
# `/s/redirect`. See AGENTS.md before adding another exception.
_API_URL = "https://wolcc-search.funnelback.squiz.cloud/s/search.json"
_COLLECTION = "wolcc~sp-wollongong-city-council-council-business-papers"
_PROFILE = "wollongong-city-council-council-business-papers-search"
# A year holds about 45 papers once items are excluded; more than this many
# means the response was cut short, which raises rather than losing meetings.
_NUM_RANKS = 500

# Each result's `docType` says what it is. For every Council meeting since
# 2020 the collection holds three papers:
#   "consolidated" (from 2020; "business paper" before and now and then
#       since): the business paper, with every report. This is the agenda.
#   "agenda": the order of business alone, about 100 KB. Used only when a
#       meeting has no business paper (2 Feb 2026, 26 Sep 2022).
#   "minutes".
# "item" (one PDF per report) and "attachment" are not papers of their own.
_BUSINESS_PAPER = {"consolidated", "business paper"}
_AGENDA = {"agenda"}
_MINUTES = {"minutes"}
# Titles that the docType gets wrong or that are not a meeting's paper:
# "Item 8 - December 2023 Financials" is typed "agenda" (5 Feb 2024); "TEST
# PDF" and "Test Document - Link" are typed "consolidated" and "agenda" (7 Apr
# 2025); a separate attachments volume was typed "business paper" (23 Jul
# 2018); and the Traffic Committee's minutes were typed "minutes" on a Council
# date (10 Dec 2018). This collection is Council's papers only, so a title
# naming a committee is another body's.
_NOT_PAPERS = re.compile(r"^\s*item\b|\btest\b|attachment|committee", re.IGNORECASE)

_TITLE_DATE = re.compile(
    r"\b(\d{1,2})[\s-]+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)[\s-]+(\d{4})\b",
    re.IGNORECASE,
)


def _first(metadata: dict, key: str) -> str:
    values = metadata.get(key) or []
    return values[0].strip() if values and isinstance(values[0], str) else ""


def _title_date(title: str) -> date | None:
    match = _TITLE_DATE.search(title)
    if not match:
        return None
    try:
        return datetime.strptime(" ".join(match.groups()), "%d %B %Y").date()
    except ValueError:
        return None


@register_scraper
class WollongongScraper(BaseScraper):
    # Cloudflare fronts both hosts and challenges GitHub's runners outright.
    # A throwaway-branch probe on ubuntu-latest (26 Oct 2026) got 403
    # `cf-mitigated: challenge` for every request: this scraper's search.json
    # URL through DefaultFetcher for 2024, 2025 and 2026, with and without
    # its header set, robots.txt on all three hosts, and six document PDFs
    # on www and the bare host. From a home connection DefaultFetcher's
    # header set gets 200. The scraper requests only
    # wolcc-search.funnelback.squiz.cloud, which is therefore the one host
    # the home proxy must allow.
    egress = "residential"

    def __init__(self):
        super().__init__("wollongong", "NSW", _BASE_URL)

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(set(years_filter))
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _year_url(year: int) -> str:
        query = urllib.parse.urlencode(
            [
                ("collection", _COLLECTION),
                ("profile", _PROFILE),
                ("num_ranks", _NUM_RANKS),
                ("smeta_year_or", year),
                ("smeta_docType_not", "item"),
            ]
        )
        return f"{_API_URL}?{query}"

    def _papers(self, year: int) -> list[dict]:
        packet = json.loads(self.fetcher.fetch_with_requests(self._year_url(year)))[
            "response"
        ]["resultPacket"]
        results = packet.get("results") or []
        total = (packet.get("resultsSummary") or {}).get("totalMatching") or 0
        if total > len(results):
            raise RuntimeError(
                f"{self.council_name}: {year} has {total} papers but the API "
                f"returned {len(results)}; raise _NUM_RANKS"
            )
        return results

    def _classify(self, result: dict) -> tuple[date, str, str, str] | None:
        """(meeting date, kind, title, url) for a meeting's paper, else None."""
        metadata = result.get("listMetadata") or {}
        doc_type = _first(metadata, "docType").lower()
        if doc_type in _BUSINESS_PAPER:
            kind = "business_paper"
        elif doc_type in _AGENDA:
            kind = "agenda"
        elif doc_type in _MINUTES:
            kind = "minutes"
        else:
            return None

        title = _first(metadata, "title") or (result.get("title") or "").strip()
        if _NOT_PAPERS.search(title):
            self.logger.info(f"{self.council_name}: not a meeting paper: {title!r}")
            return None

        url = _first(metadata, "url") or (result.get("liveUrl") or "").strip()
        host = urllib.parse.urlsplit(url).hostname or ""
        if not url.startswith("https://") or not (
            host == "wollongong.nsw.gov.au" or host.endswith(".wollongong.nsw.gov.au")
        ):
            self.logger.warning(
                f"{self.council_name}: unexpected URL {url!r} for {title!r}"
            )
            return None

        # `dateSort` (20261026) is the meeting date, the same day as
        # `meetingDate` ("26 Oct 2026") in a sortable form.
        try:
            when = datetime.strptime(_first(metadata, "dateSort"), "%Y%m%d").date()
        except ValueError:
            try:
                when = datetime.strptime(
                    _first(metadata, "meetingDate"), "%d %b %Y"
                ).date()
            except ValueError:
                self.logger.warning(
                    f"{self.council_name}: no meeting date for {title!r}"
                )
                return None

        # A paper filed under another meeting's date names its own: the 7 May
        # 2018 business paper is filed on 28 May 2018. The record has one
        # agenda slot, so a paper whose title disagrees is left off rather
        # than put on the wrong meeting. A title the regex cannot read ("6
        # February 20223", 2023's typo) is trusted to the filed date.
        named = _title_date(title)
        if named and named != when:
            self.logger.info(
                f"{self.council_name}: {title!r} is filed on {when}; left out"
            )
            return None
        return when, kind, title, url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        years = self._wanted_years()

        meetings: dict[date, dict[str, tuple[int, str]]] = {}
        extraordinary: set[date] = set()
        last_error: Exception | None = None
        read_any = False
        for year in years:
            try:
                results = self._papers(year)
            except Exception as e:
                self.logger.warning(f"{self.council_name}: could not read {year}: {e}")
                last_error = e
                continue
            read_any = True
            for result in results:
                paper = self._classify(result)
                if not paper:
                    continue
                when, kind, title, url = paper
                if when.year != year:
                    continue
                if "extraordinary" in title.lower():
                    extraordinary.add(when)
                # Two papers of one kind for a meeting is a re-upload; the
                # later asset (the higher id) is the corrected one.
                asset = int(_first(result.get("listMetadata") or {}, "assetId") or 0)
                papers = meetings.setdefault(when, {})
                kept = papers.get(kind)
                if kept is None or asset > kept[0]:
                    papers[kind] = (asset, url)

        if not read_any and last_error is not None:
            raise last_error

        results = []
        for when, papers in sorted(meetings.items()):
            agenda = papers.get("business_paper") or papers.get("agenda")
            agenda_url = agenda[1] if agenda else None
            minutes_url = papers["minutes"][1] if "minutes" in papers else None
            name = (
                "Extraordinary Meeting of Council"
                if when in extraordinary
                else "Ordinary Meeting of Council"
            )
            results.append(
                ScraperReturn(
                    name=name,
                    date=when.strftime("%d %B %Y"),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            today = clock.today()
            if years == [today.year] and today.month < 3:
                # Council's first meeting of a year is in February, and its
                # business paper is published about a week before.
                self.logger.warning(
                    f"{self.council_name}: no papers for {today.year} yet"
                )
                return []
            raise RuntimeError(f"{self.council_name}: no meetings for {years}")

        self.logger.info(f"{self.council_name} found {len(results)} meetings")
        return results
