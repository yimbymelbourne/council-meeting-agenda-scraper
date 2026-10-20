import json
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlencode, urljoin

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_BASE_URL = "https://www.subiaco.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/your-council/council-business/council-meetings-minutes"
    "/agendas-and-minutes/"
)
_DELIVERY_API = f"{_BASE_URL}/umbraco/delivery/api/v2/content"

# The listing page renders a React `MeetingList` client-side from Umbraco's
# Content Delivery API, rooted at this node (the `parentId` in the
# component's data-props). Every meeting is a `meeting` node with its
# documents expanded inline, so the whole archive—192 meetings, 2 MB—is one
# request, and `filter=year:<y>` narrows it to one year server-side.
#
# The archive starts in 2021. Older agendas were linked from search engines
# under /docs/Agendas-and-Minutes/<year>/, but nothing under the site root
# (8,071 content nodes) is a meeting or document older than 2021, and that
# path now 404s, so there is nothing earlier to fetch.
_MEETINGS_PARENT = "f14750b6-21fd-44fb-b628-d13789904428"
_PAGE_SIZE = 1000

# Each meeting carries a dozen document slots: "Agenda", "Minutes",
# "Attachments", "Discussion Notes", "Public Statements", "Alternatives &
# Amendments", and confidential versions of most of them. Only the first two
# are the meeting's own papers.
_AGENDA_TITLE = re.compile(r"^agenda$", re.IGNORECASE)

# Routes that 404 on the council's own site, whose /media/ file is behind the
# login, so there is no public URL to give instead. Leaving one out keeps a
# dead link out of the data; the meeting's other paper still comes through.
# Re-check by HEAD now and then—the council may repair them. Checked October
# 2026, out of all 267 routes the scraper otherwise emits.
_BROKEN_ROUTES = {
    # Special Council Meeting, 19 October 2021: the minutes route works.
    "/docs/agendas-and-minutes/2021/october/special-council-meeting/agenda/",
}

# Meeting-type classifications that outlived a rename. WA's local government
# reforms turn audit committees into Audit, Risk and Improvement Committees;
# Subiaco's meetings from November 2025 are titled that way but still
# classified under the old name, so the title wins for them.
_RENAMED = {
    "Audit and Risk Committee": re.compile(
        r"^Audit, Risk and Improvement Committee\b", re.IGNORECASE
    ),
}
_MINUTES_TITLE = re.compile(r"^(?:un)?(?:confirmed )?minutes$", re.IGNORECASE)


@register_scraper
class SubiacoScraper(BaseScraper):
    def __init__(self):
        super().__init__("subiaco", "WA", _BASE_URL)

    def _query(self, year: Optional[int], take: Optional[int] = None) -> list:
        """Every meeting node, or one year's when `year` is given, or just the
        first `take` of them."""
        items = []
        skip = 0
        while True:
            params = [
                ("fetch", f"descendants:{_MEETINGS_PARENT}"),
                ("filter", "contentType:meeting"),
            ]
            if year is not None:
                params.append(("filter", f"year:{year}"))
            params += [
                ("expand", "properties[meetingDocuments]"),
                ("skip", str(skip)),
                ("take", str(take or _PAGE_SIZE)),
            ]
            body = json.loads(
                self.fetcher.fetch_with_requests(
                    f"{_DELIVERY_API}?{urlencode(params)}"
                )
            )
            page = body.get("items") or []
            items.extend(page)
            skip += len(page)
            if not page or skip >= body.get("total", 0) or (take and skip >= take):
                return items

    @staticmethod
    def _public_pdf(document: dict) -> Optional[str]:
        properties = document.get("properties") or {}
        # The API hands confidential documents to anyone who asks; the site's
        # own front end is what hides them, by dropping anything restricted
        # to councillors. Do the same.
        if properties.get("restrictToCouncillorsOnly"):
            return None
        files = properties.get("documentFile") or []
        # A few Disability Access and Inclusion Committee papers are Word
        # files. The PDF fields only ever hold a PDF, so those are left out
        # rather than passed off as one.
        if not files or (files[0].get("extension") or "").lower() != "pdf":
            return None
        # Link the document node's route, as the site does, not the file's
        # /media/ URL: /media/ answers every client—browser-shaped or not—
        # with a 302 to the staff login page, while the route
        # (/docs/agendas-and-minutes/2026/february/ordinary-council-meeting/
        # agenda/) serves the PDF itself. Checked by HEAD on all 267 routes
        # emitted (October 2026): 266 are application/pdf; the 19 October
        # 2021 Special Council agenda 404s on the site itself, and is now
        # left out (see _BROKEN_ROUTES).
        path = (document.get("route") or {}).get("path")
        if not path or path in _BROKEN_ROUTES:
            return None
        return urljoin(_BASE_URL, path)

    @staticmethod
    def _meeting_name(properties: dict) -> str:
        # The meeting-type classification is the clean name. The free-text
        # title carries typos ("Commitee", "Sustainabilty") and status
        # suffixes ("- Cancelled", "- via Zoom").
        title = re.split(r"\s+-\s+", (properties.get("meetingTitle") or "").strip())[0]
        for meeting_type in properties.get("meetingType") or []:
            name = (meeting_type.get("name") or "").strip()
            if name:
                renamed = _RENAMED.get(name)
                if renamed and renamed.match(title):
                    return renamed.match(title).group(0)
                return name
        return title or "Council Meeting"

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            items = [item for year in sorted(years_filter) for item in self._query(year)]
        else:
            items = self._query(None)

        # An empty list counts as a working council in the nightly run, so
        # an empty answer has to be told apart from a broken source. A year
        # can be honestly empty: in October 2026 there was no 2027 meeting
        # node yet, so the first weeks of a year may find nothing. One probe
        # of the whole archive settles it—if that is empty too, the API or
        # the parent node has changed, and that is raised, not returned.
        if not items:
            if not years_filter or not self._query(None, take=1):
                raise RuntimeError(
                    f"{self.council_name}: {_DELIVERY_API} returned no meetings "
                    f"under {_MEETINGS_PARENT}"
                )
            self.logger.warning(
                f"{self.council_name}: no meetings listed yet for "
                f"{sorted(years_filter)}; the archive itself still answers"
            )
            return []

        # A route is built from the month and the meeting type, so two
        # meetings of one type in one month can claim the same route: Special
        # Council met on 19 and 26 October 2021 and both meetings' attachments
        # sit at /docs/agendas-and-minutes/2021/october/special-council-
        # meeting/attachments/. Only one document can answer there, and
        # nothing says which, so a shared route is not emitted.
        claims = Counter(
            (document.get("route") or {}).get("path")
            for item in items
            for document in (item.get("properties") or {}).get("meetingDocuments") or []
        )

        results = []
        for item in items:
            properties = item.get("properties") or {}
            # Midnight with no offset: the meeting's local date.
            date = (properties.get("meetingDate") or "")[:10]
            if not date:
                continue

            agenda_url = None
            minutes_url = None
            for document in properties.get("meetingDocuments") or []:
                title = (document.get("properties") or {}).get("documentTitle") or ""
                if _AGENDA_TITLE.match(title.strip()):
                    kind = "agenda"
                elif _MINUTES_TITLE.match(title.strip()):
                    kind = "minutes"
                else:
                    continue
                url = self._public_pdf(document)
                if not url:
                    continue
                if claims[(document.get("route") or {}).get("path")] > 1:
                    self.logger.warning(
                        f"{self.council_name}: {url} is the route of more than one "
                        f"document; left out of {item.get('name')!r}"
                    )
                    continue
                if kind == "agenda" and agenda_url is None:
                    agenda_url = url
                elif kind == "minutes" and minutes_url is None:
                    minutes_url = url

            # Future meetings are listed months ahead, before any papers.
            if not agenda_url and not minutes_url:
                continue

            results.append(
                ScraperReturn(
                    name=self._meeting_name(properties),
                    date=date,
                    time=None,
                    # The API's per-meeting route has no page behind it (404).
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
