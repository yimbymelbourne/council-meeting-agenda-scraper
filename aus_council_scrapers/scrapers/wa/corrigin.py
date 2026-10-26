import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import _MEETING_PATH
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)


@register_scraper
class CorriginScraper(WheatbeltCouncilConnectScraper):
    """Shire of Corrigin—documents on the year listing itself, in an older
    CouncilConnect template.

    The listing links each meeting's PDFs, as East Fremantle's does, so no
    meeting page is fetched and a production year is three requests: two
    listing pages and the upcoming page. But the markup is not the one the
    base's inline reader expects. Each meeting is a `council-meeting-info`
    block with the name in an `h2` inside the title link, the date in a bare
    `h3` (no `meeting-date` class, and no time), and the documents in
    `ul.meeting-documents-summary`. The upcoming page uses the same block,
    with the date in an `h4`, and carries the agenda as soon as it is up, so
    it is read the same way rather than through each meeting's page.

    Every PDF link on the listing and the meeting page is under
    `/Profiles/corrigin/assets/moduledata/`, which robots.txt disallows
    (`/Profiles/corrigin/Assets/ModuleData/`). Nothing is fetched there: the
    base's version-free `<meeting page>/documents/<file>` address is emitted
    instead, which is allowed and answers with the same PDF.

    Meetings from 2020 and 2021 are listed with no documents, and 2022–2023
    with agendas only (and those for a few months each year). Their
    minutes are not online anywhere found: the site's Document Centre has
    categories for the committees and the electors' meeting but none for
    Council minutes (checked 20 Oct 2026).

    Every meeting type is read, the Audit, Risk and Improvement Committee
    included: the documents are on the listing, so a committee meeting
    costs nothing extra.
    """

    inline_documents = True

    def __init__(self):
        super().__init__("corrigin", "WA", "https://www.corrigin.wa.gov.au")

    def _meeting_from_summary(
        self, summary, page_url: str, labels: dict
    ) -> Optional[ScraperReturn]:
        info = summary.find(class_="council-meeting-info") or summary
        return self._meeting_from_info(info, page_url, labels)

    def _meeting_from_info(
        self, info, page_url: str, labels: dict
    ) -> Optional[ScraperReturn]:
        title = info.find("a", class_="meeting-title", href=True)
        if title is None:
            self.logger.warning(f"Meeting with no title link on {page_url}")
            return None
        detail_url = urljoin(page_url, title["href"]).rstrip("/")
        match = _MEETING_PATH.match(urlparse(detail_url).path)
        if match is None:
            self.logger.warning(f"Not a meeting page: {detail_url}")
            return None

        date = None
        for heading in info.find_all(["h3", "h4"]):
            if heading.find_parent("a") is title:
                continue
            date, _ = self._parse_when(heading.get_text(" ", strip=True))
            if date:
                break
        if date is None:
            self.logger.warning(f"Undated meeting on {page_url}: {detail_url}")
            return None

        links = []
        for link in info.select("ul.meeting-documents-summary a[href]"):
            label = link.get("title") or link.get_text(" ", strip=True)
            label = re.sub(r"^Click to download\s+", "", label)
            links.append(
                (None, label, self._stable_document_url(detail_url, link["href"]))
            )
        agenda_url, minutes_url = self._pick_documents(links)
        if not agenda_url and not minutes_url:
            return None

        return ScraperReturn(
            name=self._name(
                title.get_text(" ", strip=True), match.group("type"), labels
            ),
            date=date.isoformat(),
            time=None,
            webpage_url=detail_url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def _upcoming_from(self, url: str, wanted: set[int], seen: set[str]):
        # Not caught, like the year listings: losing this page loses every
        # meeting whose agenda is out but whose date has not yet passed.
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        labels = {**self._labels, **self._type_labels(soup)}
        results = []
        for info in soup.select(".council-meeting-info"):
            meeting = self._meeting_from_info(info, url, labels)
            if meeting is None or meeting.webpage_url in seen:
                continue
            seen.add(meeting.webpage_url)
            if parse_date(meeting.date).year in wanted:
                results.append(meeting)
        return results
