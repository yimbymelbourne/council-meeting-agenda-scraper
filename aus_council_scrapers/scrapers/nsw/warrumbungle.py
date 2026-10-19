"""Warrumbungle Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2021, and its
year filter is exact: the per-year counts add up to the unfiltered listing's
70 results (checked 20 October 2026). The filter also offers 2018, which is
empty, so nothing before 2021 is online here.

Each row links a page of its own, but it also carries a ``data-cvid`` and the
renderer answers for it (checked 20 October 2026), so the cheaper renderer
payload is read rather than the meeting's page (``detail_pages`` stays off).

Papers are filed under ``div.meeting-document`` headings with every link
labelled "Download PDF", so ``papers_by = "heading"``—but until late 2024
the agenda's heading is "Business Paper", the NSW name for it, and it still
is on most meetings since (the 12 December 2024 one says "Agenda").
Heading mode only knows "Agenda", so a "Business Paper" heading is read as
one (`papers`). The other headings—"Attachments", "Recording" (a Zoom
link), "Quarterly Budget Review Statement 1st Quarter"—are not papers.

Two headings needed more than that. The 21 November 2024 meeting puts the
date first—"21 November Minutes", "21 November Meeting Attachments"—so a
leading day and month are stripped. And the 15 June 2023 "Minutes" heading
holds the meeting's running sheet, "meeting-schedule_150623.pdf", whose
first page reads "SCHEDULE … Public Forum … Council Meeting Commences";
that meeting has no minutes online, and a file named as a schedule is never
taken for a paper (`_NOT_A_PAPER_FILE`).

Meeting types are Ordinary and Special Meetings only, so nothing is
filtered: one production year is about 11 requests. The site is behind
Akamai (``Server-Timing: ak_p``), which served the identifying User-Agent
without a challenge from a home IP; it has not been measured from a GitHub
runner. robots.txt disallows nothing on the meetings pages.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_BUSINESS_PAPER = re.compile(r"^\s*business\s+papers?\b", re.IGNORECASE)

# "21 November Minutes": a day and month ahead of the paper's name.
_LEADING_DAY = re.compile(
    r"^\s*\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+",
    re.IGNORECASE,
)

_NOT_A_PAPER_FILE = re.compile(r"schedule", re.IGNORECASE)


@register_scraper
class WarrumbungleScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 19 s
    # (11 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 19

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "warrumbungle",
            "NSW",
            "https://www.warrumbungle.nsw.gov.au/Our-Council/Council-Meetings/Agendas-Minutes-and-Recordings",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            renamed = _LEADING_DAY.sub("", text, count=1)
            renamed = _BUSINESS_PAPER.sub("Agenda", renamed, count=1)
            if renamed != text:
                heading.string = renamed
        for anchor in content.find_all("a", href=True):
            if _NOT_A_PAPER_FILE.search(anchor["href"].rsplit("/", 1)[-1]):
                anchor.decompose()
        return super().papers(content)
