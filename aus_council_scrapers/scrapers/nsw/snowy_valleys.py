"""Snowy Valleys Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every Ordinary and Extraordinary
meeting from 2016, upcoming ones included, ten to a page with a year filter.
Those are the only two meeting types, so nothing is allowlisted.

Papers are filed under headings, so ``papers_by = "heading"``. Each meeting
has three: "Agenda", a short order of business (about 150 KB) with an
HTML version beside it; "Business Paper", the agenda with the officers' reports,
followed by each item's attachments; and "Minutes". The business paper is
stored as the agenda—the base class ranks it above a bare "Agenda"—because
the reports are what the order of business leaves out. Some minutes headings
lead with the date ("20 August 2026 - Minutes", "16 November 2023 -
Minutes"), which the base class strips before matching.

The 15 October 2026 meeting is listed twice, with two cvids: one of them a
copy an editor left in a sandbox folder. Both carry the same business paper,
so the base class merges them into one record.

The payloads still link most papers from before about 2025 at paths the
council has since moved: ``.../v/1/meeting-minutes-amp-agendas/council-
meetings/20201015/20201015-business-paper-ordinary-council.pdf`` is a 404,
and the same file is served from ``.../council-meetings/2020/20201015/...``.
Each versioned link with a bare ``<yyyymmdd>`` folder is therefore given
its year folder (`_in_year_folder`). Checked 20 October 2026 against all 182
links the full history stores: 75 were 404s that the year folder fixes, 47
work both ways, and none that worked stopped working. The one unversioned
link (18 June 2020's minutes, ``/files/assets/public/meeting-minutes-amp-
agendas/...``) works as it is and 404s with a year folder, so unversioned
links are left alone. 28 January 2020's minutes are under ``council-
meetings/council-meeting-minutes/``; that versioned link is a 404 and the
unversioned one serves the file, so a versioned link in a folder that is
neither a year nor a date loses its version.

robots.txt disallows each meeting's own HTML pages (``/Council/Council-
Meetings/<date>-Ordinary-Meeting/...``), which this never requests; the
listing, the renderer and ``/files/`` are allowed.

One production year is 14 requests: the listing filtered to that year at
``page_size`` 50 (13 meetings in 2026), then a payload per meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# ".../public/v/1/meeting-minutes-amp-agendas/council-meetings/" and the
# folder after it.
_VERSIONED_FOLDER = re.compile(
    r"(/files/assets/public/)v/\d+/"
    r"(meeting-minutes-amp-agendas/council-meetings/)([^/]+)/"
)


def _in_year_folder(url: str) -> str:
    """The link at the path the council's site now serves it from. See the
    module docstring."""

    def fix(match: re.Match) -> str:
        public, meetings, folder = match.groups()
        if re.fullmatch(r"\d{4}", folder):
            return match.group(0)
        if re.fullmatch(r"(\d{4})\d{4}", folder):
            year = folder[:4]
            return match.group(0).replace(
                f"{meetings}{folder}/", f"{meetings}{year}/{folder}/"
            )
        return f"{public}{meetings}{folder}/"

    return _VERSIONED_FOLDER.sub(fix, url, count=1)


@register_scraper
class SnowyValleysScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 26 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # The busiest year since 2020 is 16 meetings, so every year is one
    # listing page.
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "snowy_valleys",
            "NSW",
            "https://www.snowyvalleys.nsw.gov.au/Council/Council-Meetings",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        return {
            kind: _in_year_folder(url) for kind, url in super().papers(content).items()
        }
