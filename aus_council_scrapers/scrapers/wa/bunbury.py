import datetime
import json
import re
from typing import Optional
from urllib.parse import urlencode

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import filename_of, find_date, text_without_date
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.bunbury.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/live/your-council/meetings-and-minutes"
# The meetings page is a Next.js front end over headless WordPress, and
# renders from the site's own JSON route: one "minutes" post per meeting,
# twelve to a page, filtered server-side by year and category and paged by
# cursor (`cursor=<endCursor>&direction=after`; `direction=next` answers
# 500). robots.txt is `Allow: /`, so /api/ is open.
_API_URL = f"{_BASE_URL}/api/posts/minutes/"

# Only the Council category: Ordinary and Special Council Meetings, and the
# electors' meetings the council files with them. The other categories are
# committees: advisory and review groups (heritage, events, youth,
# international relations, audit, CEO performance) and the Policy Review and
# Development Committee ("PRDC 14 October 2026"), a standing committee of
# councillors that meets about every second month to review council
# policies. None of them decides development applications—WA's development
# assessment panels sit outside council—so they are left out, PRDC with
# them; whether PRDC belongs in the output, since the policies it reviews
# can include planning policies, is an open question for the project.
# Filtering on the server keeps a production year at two requests instead
# of four.
_CATEGORY = "council"
# A guard, not an expectation: a busy year is two pages.
_MAX_PAGES = 10

# Each post's title is an abbreviation and the date ("OCM 16 December
# 2025"); its notes are the documents, typed "agenda", "minutes" or
# "appendices", with a description and a PDF on cdn.bunbury.wa.gov.au.
_ABBREVIATIONS = {
    "OCM": "Ordinary Council Meeting",
    "SCM": "Special Council Meeting",
    "AEGM": "Annual General Meeting of Electors",
    "SME": "Special Meeting of Electors",
}
_TITLE = re.compile(r"^([A-Z]{2,6})\s+\d")
# The "minutes" slot also carries the meeting's video ("Meeting Recording for
# Ordinary Council Meeting ..."), as an embed rather than a file, and now and
# then a report appendix (24 September 2024's "Appendix 10.4.2-A Strategic
# Advocacy Priorities"). The description says what a document is, so a
# described document that names neither an agenda nor minutes is skipped;
# the type decides only when there is no description.
_RECORDING = re.compile(r"recording|video", re.IGNORECASE)
_AGENDA = re.compile(r"^agenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_DESCRIPTION_NAME = re.compile(
    r"^(?:agenda(?: and appendices)?|(?:un)?confirmed minutes|minutes)\s+(?:for|of)\s+",
    re.IGNORECASE,
)


@register_scraper
class BunburyScraper(BaseScraper):
    def __init__(self):
        super().__init__("bunbury", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _posts(self, year: int) -> list[dict]:
        posts: list[dict] = []
        cursor = None
        for _ in range(_MAX_PAGES):
            params = {"category": _CATEGORY, "year": year}
            if cursor:
                params.update({"cursor": cursor, "direction": "after"})
            data = json.loads(
                self.fetcher.fetch_with_requests(f"{_API_URL}?{urlencode(params)}")
            )
            posts.extend(data.get("posts") or [])
            pagination = data.get("pagination") or {}
            if not pagination.get("hasNextPage") or not pagination.get("endCursor"):
                return posts
            cursor = pagination["endCursor"]
        self.logger.warning(
            f"Bunbury: stopped paging {year} after {_MAX_PAGES} pages; later "
            "meetings were not read"
        )
        return posts

    @staticmethod
    def _documents(post: dict) -> list[tuple[str, str, str]]:
        """``(kind, description, pdf_url)`` for each agenda or minutes note."""
        documents = []
        for note in (post.get("minutes") or {}).get("notes") or []:
            url = (note.get("attachmentFile") or {}).get("mediaItemUrl") or ""
            if not filename_of(url).lower().endswith(".pdf"):
                continue
            description = re.sub(r"\s+", " ", note.get("description") or "").strip()
            if _RECORDING.search(description) or note.get("type") == "appendices":
                continue
            if _AGENDA.search(description):
                kind = "agenda"
            elif _MINUTES.search(description):
                kind = "minutes"
            elif not description and note.get("type") in ("agenda", "minutes"):
                kind = note["type"]
            else:
                continue
            documents.append((kind, description, url))
        return documents

    @staticmethod
    def _filename_date(url: str) -> Optional[datetime.date]:
        found = find_date(re.sub(r"[-_]+", " ", filename_of(url)))
        return found[0] if found else None

    def _for_this_meeting(
        self, url: Optional[str], date: datetime.date
    ) -> Optional[str]:
        """None for a document whose filename names another meeting's day.

        SCM 28 October 2025's minutes slot holds
        ``Confirmed-Minutes-for-OCM-30-September-2025.pdf``. Day and month
        are compared; a filename naming no date is given the benefit of the
        doubt.
        """
        named = self._filename_date(url) if url else None
        if named and (named.month, named.day) != (date.month, date.day):
            self.logger.info(f"Bunbury: {filename_of(url)} is not {date}; dropped")
            return None
        return url

    @staticmethod
    def _name_from_description(description: str) -> Optional[str]:
        name = text_without_date(_DESCRIPTION_NAME.sub("", description))
        return name or None

    def _meeting(self, name, date, agenda_url, minutes_url) -> ScraperReturn:
        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def _from_post(self, post: dict) -> list[ScraperReturn]:
        title = (post.get("title") or "").strip()
        documents = self._documents(post)
        stamped = (post.get("minutes") or {}).get("minutesDate")
        match = _TITLE.match(title)
        if match and stamped:
            # One meeting. Its date is the post's own minutesDate, which the
            # title repeats; a description can be wrong (SCM 28 July 2026's
            # minutes are described as "18 July 2026").
            date = datetime.date.fromisoformat(stamped[:10])
            name = _ABBREVIATIONS.get(match.group(1))
            if name is None:
                name = next(
                    (
                        n
                        for _, d, _ in documents
                        for n in [self._name_from_description(d)]
                        if n
                    ),
                    match.group(1),
                )
            agenda_url = next(
                (
                    u
                    for k, _, u in documents
                    if k == "agenda" and self._for_this_meeting(u, date)
                ),
                None,
            )
            minutes_url = next(
                (
                    u
                    for k, _, u in documents
                    if k == "minutes" and self._for_this_meeting(u, date)
                ),
                None,
            )
            if not agenda_url and not minutes_url:
                return []
            return [self._meeting(name, date, agenda_url, minutes_url)]

        # Before the site was rebuilt in 2022 a year's minutes were loaded as
        # one post: "Confirmed Minutes 2021", dated 1 January, holding every
        # 2021 meeting's minutes. Each document is then its own meeting,
        # named by its description ("Confirmed Minutes for Ordinary Council
        # Meeting 9 February 2021") and dated by its filename, falling back to
        # the description: the electors' meeting is described as 2 February
        # 2021, but its file and its minutes' cover say 16 February. A
        # document dated by neither is left out: 1 January is the post's
        # date, not a meeting's.
        meetings = []
        for kind, description, url in documents:
            found = find_date(description)
            date = self._filename_date(url) or (found[0] if found else None)
            name = self._name_from_description(description)
            if not date or not name:
                self.logger.warning(
                    f"Bunbury: cannot date {description!r} in post {title!r}; skipped"
                )
                continue
            meetings.append(
                self._meeting(
                    name,
                    date,
                    url if kind == "agenda" else None,
                    url if kind == "minutes" else None,
                )
            )
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        failures = []
        for year in sorted(wanted, reverse=True):
            try:
                posts = self._posts(year)
            except Exception as e:
                # One year failing in a multi-year run should not cost the
                # others; every requested year failing is raised below.
                self.logger.warning(f"Bunbury: {year} failed: {e}")
                failures.append(e)
                continue
            for post in posts:
                for meeting in self._from_post(post):
                    key = (meeting.name, meeting.date)
                    if key in seen or meeting.cleaned_date.year not in wanted:
                        continue
                    seen.add(key)
                    results.append(meeting)
        if failures and len(failures) == len(wanted):
            raise failures[-1]

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
