import re

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.wheatbelt_councilconnect import (
    WheatbeltCouncilConnectScraper,
)

_DATE = r"\d{1,2}\s+[A-Za-z]+\s+\d{4}"
# "28 April 2021 - OCM - RESCHEDULED to 3 May 2021", "Rescheduled from 27
# July 2022 - Ordinary Council Meeting - Now - 3 August 2022": the date the
# meeting was moved to, which is the day it was held.
_MOVED_TO = re.compile(rf"\b(?:rescheduled\s+to|now)\s*[-–—]?\s*({_DATE})", re.I)
# "... (Rescheduled from 24 June 2026)", "... (Meeting rescheduled from
# Wednesday 25 June 2025)": the date it was moved from, which is not.
_MOVED_FROM = re.compile(
    rf"\(?\s*(?:meeting\s+)?rescheduled\s+from\s+(?:[A-Za-z]+day\s+)?{_DATE}\s*\)?",
    re.I,
)


# "Confirmed SCM- 13 February 2023", "Public Confirmed SCM - 17 October
# 2022", "Confirmed Special Council Meeting - 8 September 2023": the
# confirmed minutes, under a "Downloads" heading and never called minutes
# (the first two read 20 Oct 2026: both are headed "MINUTES"). The base
# reads nothing from such a label, so it is told what the document is.
_CONFIRMED_ONLY = re.compile(r"^(?:public\s+)?confirmed\b", re.IGNORECASE)
_NAMES_A_PAPER = re.compile(r"agenda|minut|notice|attach", re.IGNORECASE)


def _name_minutes(label: str) -> str:
    if _CONFIRMED_ONLY.search(label) and not _NAMES_A_PAPER.search(label):
        return f"{label} (minutes)"
    return label


@register_scraper
class VictoriaPlainsScraper(WheatbeltCouncilConnectScraper):
    """Shire of Victoria Plains—documents on each meeting's own page.

    Council meetings only. The site files its Audit, Risk and Improvement
    Committee as "Audit Council Meeting" and its electors' meeting as
    "Electors Council Meeting" (and, in 2024, "General Council Meeting");
    none of them decides planning matters, and leaving them out saves a
    request each per meeting.

    **Names.** Every meeting under the two types read is the meeting its
    type names: the headings say "Ordinary Council Meeting", or "OCM" and
    "SCM" through 2020–21, padded with a start time ("16 August 2021 -
    3.30pm - Special Council Meeting") or a reschedule note. So the type's
    name is used, never the heading's (`name_by_type`, checked across all
    2020–2026 headings, 20 Oct 2026).

    **Rescheduled meetings.** Four headings carry two dates. Where the
    heading says what the meeting was moved *to*, that is the day it was
    held: the minutes of "28 April 2021 - OCM - RESCHEDULED to 3 May 2021"
    are of the meeting on 3 May 2021, though the date field says 28 April,
    and the agenda of "Rescheduled from 27 July 2022 ... Now - 3 August
    2022" is headed "27 July 2022 (Held 3 August 2022)". The base would take
    27 July there, because the agenda's filename names it. A date the
    meeting was moved *from* is dropped before the base compares the
    heading with the date field, so it cannot outvote the real one.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    name_by_type = True

    # Read on 20 Oct 2026. The 3.30pm Special meeting's minutes cover that
    # meeting alone (opened 3.50pm, closed before the second meeting), so on
    # the 4.30pm meeting's page they are not that meeting's minutes.
    wrong_documents = {
        "https://www.victoriaplains.wa.gov.au/council-meetings/ordinary-council-meeting/rescheduled-from-27-july-2022-ordinary-council-meeting-now-3-august-2022/399/documents/scm-minutes-public-2-june-2022.pdf": (
            "Minutes of the 2 June 2022 Special Council Meeting, posted on the "
            "3 August 2022 Ordinary meeting's page beside its own minutes"
        ),
        "https://www.victoriaplains.wa.gov.au/council-meetings/special-council-meeting/16-august-2021-special-council-meeting-2-august-2021-(430pm)/379/documents/unconfirmed-minutes-scm-2-august-2021-330pm.pdf": (
            "Minutes of the 3.30pm Special Council Meeting of 2 August 2021, "
            "posted on the 4.30pm meeting's page"
        ),
    }

    # Read 20 Oct 2026: the date field of this 16 August 2021 Special
    # meeting says 11:30 PM, but its agenda and minutes are filed as the
    # "230pm" meeting (the second that day was at 3.30pm), and the minutes
    # record it opening at 2.53pm. The scheduled time is emitted.
    corrected_times = {
        "https://www.victoriaplains.wa.gov.au/council-meetings/special-council-meeting/16-august-2021-special-council-meeting/380": "2:30 PM",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s
    # (14 requests—the year listings, the upcoming page and a page per
    # meeting). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__(
            "victoria_plains", "WA", "https://www.victoriaplains.wa.gov.au"
        )

    def _pick_documents(self, links):
        return super()._pick_documents(
            [(group, _name_minutes(label), url) for group, label, url in links]
        )

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is not None and url in self.corrected_times:
            meeting.time = self.corrected_times[url]
        return meeting

    def _heading_date_if_documents_agree(self, heading, date, document_urls):
        moved_to = _MOVED_TO.search(heading)
        if moved_to:
            return parse_date(moved_to.group(1)).date()
        return super()._heading_date_if_documents_agree(
            _MOVED_FROM.sub("", heading), date, document_urls
        )
