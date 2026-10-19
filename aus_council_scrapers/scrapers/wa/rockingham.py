import re
import urllib.parse

from aus_council_scrapers.alyka import (
    KsearchScraper,
    find_date,
    find_month,
)
from aus_council_scrapers.base import ScraperReturn, register_scraper

_BASE_URL = "https://rockingham.wa.gov.au"
_MEETINGS = f"{_BASE_URL}/your-city/council/council-and-committee-meetings"
_LISTING_URL = f"{_MEETINGS}/agendas-and-minutes"
_DATES_URL = f"{_MEETINGS}/meeting-dates"
_LOCATION = (
    "Council Chamber, City of Rockingham Administration Centre, "
    "Civic Boulevard, Rockingham"
)

# Rockingham's ksearch lists one record per document—agenda, minutes,
# information bulletin, report attachments—and dates none of them to the
# day. Titles read "Ordinary Council Agenda September 2026", and the only
# date field is the day the file was *published*, which for an agenda is the
# week before the meeting and for minutes the week after.
#
# A month is not a meeting date, and a publication date is not one either, so
# neither is emitted as one. The real dates are on the council's meeting-dates
# page, which lists each body's meetings for the current year: Council on the
# fourth Tuesday, its two standing committees the week before. A document is
# kept only when its meeting type and title month find a date there. That
# leaves out:
#
#   - every year the dates page no longer lists. Their documents are still
#     published, but nothing on the site says which day those meetings fell
#     on, and the agenda PDFs that do say are tens of megabytes each. (The
#     fetcher returns decoded text, not bytes, so a ranged read of a PDF's
#     first page is not on offer without changing it.) The council's rule—
#     Council on the fourth Tuesday, committees the week before—would date
#     them, but a rule is not a record: December and specials move.
#   - special meetings, electors' meetings and the smaller committees, which
#     the dates page does not schedule.
#
# So this returns the current year's Council and committee meetings, exactly
# dated, rather than a decade of meetings dated to the nearest month.

_KINDS = {"agenda", "minutes"}
# A second agenda for a meeting that already has one.
_SUPPLEMENTARY = re.compile(r"addendum|supplementary|\blate\b", re.IGNORECASE)
_NOT_A_MEETING_WORD = re.compile(r"\b(?:meetings?|committee|ordinary)\b", re.I)
_TIME = re.compile(r"\bat\s+(\d{1,2}(?:[:.]\d{2})?\s*[ap]m)\b", re.IGNORECASE)


def _body(name: str) -> str:
    """A meeting body's name with the generic words dropped.

    The listing says "Ordinary Council Meeting" and "Planning and Asset
    Services Committee Meeting"; the dates page heads its sections "Council
    Meetings" and "Planning and Asset Services Committee". Both reduce to
    "council" and "planning and asset services".
    """
    return re.sub(r"\s+", " ", _NOT_A_MEETING_WORD.sub("", name)).strip().lower()


@register_scraper
class RockinghamScraper(KsearchScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("rockingham", "WA", _BASE_URL)

    def _schedule(self) -> dict:
        """``{(body, year, month): (date, time)}`` from the meeting-dates page.

        Each body is an accordion item: its heading names the body, a
        paragraph gives the hour ("held on the fourth Tuesday of the month at
        6pm"), and a list gives the dates.
        """
        schedule = {}
        for item in self._page(_DATES_URL).find_all(class_="accordion-item"):
            heading = item.find(class_="accordion-header")
            if not heading:
                continue
            body = _body(heading.get_text(" ", strip=True))
            time_match = _TIME.search(item.get_text(" ", strip=True))
            time = time_match.group(1) if time_match else None
            for entry in item.find_all("li"):
                found = find_date(entry.get_text(" ", strip=True))
                if found:
                    date = found[0]
                    schedule[(body, date.year, date.month)] = (date, time)
        return schedule

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        schedule = self._schedule()
        scheduled_years = {year for _, year, _ in schedule}
        years = self._wanted_years() & scheduled_years
        # Raised rather than logged, because the likely cause is a calendar
        # event, not a broken site: when the council replaces this year's
        # schedule with next year's, a run asking for this year can date
        # nothing. Returning [] would put Rockingham in council-alerts'
        # `okCouncils` with 0 meetings, where nobody looks.
        if not years:
            raise RuntimeError(
                f"{self.council_name}: the meeting-dates page lists "
                f"{sorted(scheduled_years) or 'no'} years, none of them wanted "
                f"({sorted(self._wanted_years())}); meetings it does not "
                f"schedule cannot be dated to the day"
            )

        endpoint, search_param = self._ksearch_config(self._listing_page())
        # December's minutes are published in January, under the next year.
        published = sorted(years | {year + 1 for year in years})
        records = self._ksearch(
            endpoint,
            search_param,
            [self.multiselect_filter("mnapublicationdateyear", published)],
        )

        meetings: dict[tuple, dict] = {}
        undated = 0
        for record in records:
            kind = (record.get("MNADocumentType") or "").lower()
            title = record.get("MNATitle") or ""
            url = record.get("MNAFileUrl")
            if kind not in _KINDS or not url or _SUPPLEMENTARY.search(title):
                continue

            meeting_type = record.get("MNAMeetingType") or ""
            month = find_month(title)
            slot = schedule.get((_body(meeting_type), *month)) if month else None
            if not slot or slot[0].year not in years:
                undated += 1
                continue

            url = urllib.parse.urljoin(_BASE_URL, url)
            meeting = meetings.setdefault(
                (meeting_type, slot[0]), {"time": slot[1], "documents": {}}
            )
            # Records arrive newest first, so a re-issued document wins.
            meeting["documents"].setdefault(kind, url)

        if undated:
            self.logger.info(
                f"{self.council_name}: skipped {undated} agenda/minutes "
                f"document(s) whose meeting the dates page does not list"
            )

        results = []
        for (meeting_type, date), meeting in sorted(
            meetings.items(), key=lambda m: m[0][1], reverse=True
        ):
            result = self._meeting(
                name=meeting_type,
                date=date,
                webpage_url=_LISTING_URL,
                agenda_url=meeting["documents"].get("agenda"),
                minutes_url=meeting["documents"].get("minutes"),
                time=meeting["time"],
                location=_LOCATION,
            )
            if result:
                results.append(result)

        self._log_result(results, f"{len(records)} listed documents")
        return results
