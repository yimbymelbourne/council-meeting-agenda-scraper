"""Clare and Gilbert Valleys Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper` and
`RegionalLGASAScraper`. One page lists the whole collection—council, its
committees and panels, the Mid North Regional Assessment Panel and the s 41
committees—so one request covers a production year.

The committee labels are named after their pages ("Ordinary & Special
Council Meetings", "Audit & Risk Committee Meetings"), so they are mapped to
meeting types here.

Three kinds of paper are left out:

- **Briefing sessions and workshops.** Informal gatherings, at which no
  decisions may be made; their papers are notices and programs.
- **The s 41 committees that run a facility or a service**: the Riverton
  Recreation Ground, Auburn Recreation Park, Clare Town Hall, Auburn
  Institute Hall and Mid North Community Passenger Network committees.
  Their papers are mostly monthly financial statements, and their agendas
  and minutes are filed a month apart often enough that most of their
  meetings came back with one paper. Their AGMs were also named "Annual
  General Meeting", as if the council's own. Council's other committees are
  kept.
- **Released confidential papers under the council's own label.** The
  council files a "Confidential Minutes Released" for most meetings, beside
  the public minutes, and where one is filed on a day of its own it became
  a council meeting that never happened (3 April 2024 is the CEO panel's
  date, 10 September 2024's paper is the passenger network committee's).
  The CEO panels keep theirs: those meetings are held in confidence, and a
  released paper is often their only one.

The CEO panel's papers are filed under two labels, "CEO Performance
Management Panel" and, from the middle of 2022, "Chief Executive Officer
Panel", sometimes both for one meeting (20 July 2022: agenda under the
first, minutes under the second). Grouped by label, each such meeting came
back as two, one paper each. So every CEO panel label is read as one body,
named as the council named it in that year: the Performance Management
Panel until 2021, the Chief Executive Officer Panel from 2022, when its
papers start calling it the "CEO Panel".
"""

import dataclasses

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.lgasa_regional import (
    CONFIDENTIAL_TITLES,
    INFORMAL_TITLES,
    RegionalLGASAScraper,
)

_COUNCIL_LABEL = "Ordinary & Special Council Meetings"


@register_scraper
class ClareGilbertValleysScraper(RegionalLGASAScraper):
    listing_urls = (
        "https://www.claregilbertvalleys.sa.gov.au/council-documents/"
        "clare-and-gilbert-valleys-council-agenda-and-minutes",
    )

    committee_names = {
        _COUNCIL_LABEL: COUNCIL_MEETING,
        "2020 Council Meeting Agendas": COUNCIL_MEETING,
        "Audit Committee Meetings": "Audit Committee",
        "Audit & Risk Committee Meetings": "Audit & Risk Committee",
        "Council Assessment Panel Meetings": "Council Assessment Panel",
        "CEO Selection Panel Meetings": "CEO Selection Panel",
    }

    # Every label the CEO panel's papers are filed under; see the module
    # docstring. The CEO Selection Panel is another body.
    ceo_panel_labels = frozenset(
        {
            "CEO Performance Management Panel",
            "Chief Executive Officer Panel",
            "2020 CEO Performance Review Agenda & Minutes",
            "2021 CEO Performance Review Agenda & Minutes",
        }
    )

    skip_committees = frozenset(
        {
            "Council Briefing Sessions",
            "Workshop Programs",
            "2019 Workshop Presentations",
            "2020 Workshop Presentations",
            "2024 Briefing Session Programs & Presentations",
            "Riverton Recreation Ground Committee",
            "Auburn Recreation Park Committee",
            "Clare Town Hall Committee",
            "Auburn Institute Community Hall Committee",
            "Mid North Community Passenger Network Committee",
        }
    )

    # Workshop programs are also filed under the council's label.
    skip_titles = INFORMAL_TITLES

    def _skipped(self, listed) -> bool:
        if listed.committee == _COUNCIL_LABEL and CONFIDENTIAL_TITLES.search(
            listed.title
        ):
            return True
        return super()._skipped(listed)

    def _relabel(self, listed, year):
        if listed.committee not in self.ceo_panel_labels:
            return listed
        name = (
            "CEO Performance Management Panel"
            if year <= 2021
            else "Chief Executive Officer Panel"
        )
        return dataclasses.replace(listed, committee=name)

    def __init__(self):
        super().__init__(
            "clare_gilbert_valleys", "SA", "https://www.claregilbertvalleys.sa.gov.au"
        )
