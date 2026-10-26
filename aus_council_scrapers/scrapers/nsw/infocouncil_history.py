"""The InfoCouncil archive of a council that has since moved to Resolve.

Byron and Port Macquarie-Hastings left InfoCouncil for Resolve in 2025 but
kept their `*.infocouncil.biz` sites up, with every meeting from before the
move. Resolve holds little or none of that, so each reads its InfoCouncil
years through `other_meetings` with this class.

Records come out as Resolve's do: ISO dates, times as "6:00 PM", and the
council's Resolve name for each meeting type, so that a meeting type reads
the same either side of the move. A grid row whose type is not in the
council's `names` is dropped, which is how the advisory committees, traffic
committees and released confidential reports are left out.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Optional

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, InfoCouncilScraper, ScraperReturn

# The grid's time cell as councils type it: "3:00pm", "9.00am", "2:00 PM".
# Anything else ("4.00", "12:00", or the "00am" the base class cuts out of
# "10:00am" on one PMHC row) is left as no time rather than guessed at.
_TIME = re.compile(r"^(\d{1,2})[.:](\d{2})\s*([ap])\.?m\.?$", re.IGNORECASE)


class InfoCouncilHistory(InfoCouncilScraper):
    """A Resolve council's InfoCouncil years, read through the owner's
    fetcher so that recording and replay see its requests."""

    # Folds supplementary rows onto their meeting and keeps the venue out of
    # the name; AGENTS.md asks for it on every new InfoCouncil subclass.
    tidy_meeting_rows = True

    def __init__(self, owner: BaseScraper, infocouncil_url: str, names: dict[str, str]):
        super().__init__(
            owner.council_name, owner.state, owner.base_url, infocouncil_url
        )
        self.fetcher = owner.fetcher
        self.logger = owner.logger
        self.names = names

    def meetings(self, years: list[int], before: datetime.date) -> list[ScraperReturn]:
        """The kept meetings in `years` dated before `before`, the day the
        council's Resolve record starts.

        A year page that fails is a warning, and every year failing raises
        (`InfoCouncilScraper.scraper`), so a blocked host is a failed
        council, not an empty one."""
        self.years_filter = years
        results = []
        for record in self.scraper():
            name = self.names.get(record.name or "")
            if not name:
                continue
            date = parse_date(record.date, dayfirst=True).date()
            if date >= before:
                continue
            results.append(
                dataclasses.replace(
                    record,
                    name=name,
                    date=date.isoformat(),
                    time=_clock_time(record.time),
                )
            )
        return sorted(results, key=lambda r: r.date)


def _clock_time(text: Optional[str]) -> Optional[str]:
    match = _TIME.match((text or "").strip())
    if not match:
        return None
    hour, minute, half = match.groups()
    return f"{int(hour)}:{minute} {half.upper()}M"
