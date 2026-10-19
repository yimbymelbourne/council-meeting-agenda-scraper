"""What nine small WA shires on CouncilConnect need beyond the base class.

Wongan-Ballidu, Lake Grace, Cunderdin, Gnowangerup, Meekatharra,
Jerramungup, Kellerberrin, Broomehill-Tambellup and Pingelly all keep their
papers on each meeting's own page, and all type their headings, times and
document groups by hand. Four things go wrong on them that the base class
reads at face value, so this subclass corrects them before the base sees
them or before the meeting is returned. None of it is specific to one
shire, which is why it is here and not in each module; a shire's own
quirks stay in its module, through `_fix_document` and `placeholder_time`.

- **Placeholder times.** A meeting entered without a time is shown as
  "12:00 AM" (14 of Lake Grace's 87, 8 of Gnowangerup's), and a handful are
  typed with AM for PM ("3:00 AM" at Wongan-Ballidu, whose meetings are at
  3 pm; "5:00 AM" at Cunderdin, whose are at 5 pm). No council in this set
  meets before 7 am, so a time before then is dropped rather than emitted:
  no time is better than a wrong one in an alert. The same test is applied
  to the time on an upcoming page's button, which the base uses when the
  meeting page gives none.
- **Default times.** Two shires' modules give one time to every meeting
  entered before a cut-over date: "6:00 PM" at Kellerberrin to April 2025
  and at Pingelly to 2024. Not one agenda checked says 6 pm (11 at
  Kellerberrin, 7 at Pingelly; they say 2 pm, 4 pm, 5 pm, 7 pm or 8.15 am). A
  shire with one names it in `placeholder_time`, and that time is dropped
  from meetings before the cut-over.
- **Headings that are not a meeting's name.** "Wednesday 8 February2023 -
  Special Council Meeting" (no space, so the date is not stripped), "Special
  Council Meeitng Monday, 28th July 2025, 5pm", "17 December 2021 (Friday) -
  Ordinary Meeting of Council", "19 March 2020 - Ordinary Meeting of Council
  Attachments", "Ordinary Meeting of Council - 22 November 2023
  (Rescheduled)". The date, hour, weekday, reschedule note and a stray
  "Attachments" are taken off first, and a heading whose words are all in
  the type's name ("Special Meeting" filed as a Special Council Meeting) is
  given the type's name.
- **Documents the base would misfile.** Each shire module may rewrite a
  document's group or label, or the filename the base tests, before the
  base picks the agenda and minutes; the URL emitted is always the real one.
  See `_fix_document`.

These would be at home in `CouncilConnectScraper` itself; they are here
only because this change does not edit the shared base.
"""

from __future__ import annotations

import datetime
import re
from typing import Optional

from aus_council_scrapers.councilconnect import CouncilConnectScraper

_MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december)"
)
# "February2023": a date the base's heading pattern cannot see.
_GLUED_YEAR = re.compile(rf"\b({_MONTHS})(\d{{4}})\b", re.IGNORECASE)
# "(Friday)", "(Rescheduled)": a note about the day, not the meeting.
_PAREN_NOTE = re.compile(
    r"\(\s*(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day|re-?scheduled"
    r"|postponed)\s*\)",
    re.IGNORECASE,
)
# ", 5pm" or "- 5.30 pm" at the end of a heading.
_TRAILING_HOUR = re.compile(
    r"[,\s-]*\b\d{1,2}(?:[.:]\d{2})?\s*[ap]\.?m\.?\s*$", re.IGNORECASE
)
# "... Ordinary Meeting of Council Attachments": the page is the meeting's.
_TRAILING_ATTACHMENTS = re.compile(r"[\s-]+attachments?\s*$", re.IGNORECASE)

# The earliest hour a time is believed. See the module docstring.
_EARLIEST_PLAUSIBLE_HOUR = 7


def _plausible(time: str) -> bool:
    """Whether a "3:30 PM" time is late enough to be believed."""
    return datetime.datetime.strptime(time, "%I:%M %p").hour >= _EARLIEST_PLAUSIBLE_HOUR


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


class ShireCouncilConnectScraper(CouncilConnectScraper):
    """CouncilConnect with the corrections described in the module docstring.

    `relabelled_documents`
        `{url: label}` for a document whose own label says something else,
        checked by reading it: Meekatharra's 25 October 2025 agenda is
        labelled "Attachment 10.2.1 - Financial Statement September 2025".
        The opposite of the base's `wrong_documents`.

    `placeholder_time`
        `(time, first_real_date)`: the time the module gave every meeting
        dated before `first_real_date`, which says nothing about when the
        meeting was held. Checked against the agendas; see the module
        docstring.
    """

    relabelled_documents: dict[str, str] = {}
    placeholder_time: Optional[tuple[str, datetime.date]] = None

    # --- times ---------------------------------------------------------------

    @staticmethod
    def _parse_when(text: str) -> tuple[Optional[datetime.date], Optional[str]]:
        date, time = CouncilConnectScraper._parse_when(text)
        if time and not _plausible(time):
            time = None
        return date, time

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        # The base fills a page's missing time from `fallback_when`, which on
        # the upcoming path is read from the button with no test of its own:
        # a "12:00 AM" dropped from the page would come straight back from
        # the button. Upcoming meetings are the ones alerts go out for.
        if fallback_when and fallback_when[1] and not _plausible(fallback_when[1]):
            fallback_when = (fallback_when[0], None)
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting and self.placeholder_time:
            time, first_real_date = self.placeholder_time
            if meeting.time == time and meeting.date < first_real_date.isoformat():
                meeting.time = None
        return meeting

    # --- names ---------------------------------------------------------------

    def _name(self, heading: str, type_slug: Optional[str], labels: dict) -> str:
        cleaned = _GLUED_YEAR.sub(r"\1 \2", heading or "")
        cleaned = _PAREN_NOTE.sub("", cleaned)
        cleaned = _TRAILING_HOUR.sub("", cleaned)
        cleaned = _TRAILING_ATTACHMENTS.sub("", cleaned)
        name = super()._name(cleaned, type_slug, labels)
        label = labels.get(type_slug) if type_slug else None
        if label and name != label and _words(name) <= _words(label):
            return label
        return name

    # --- documents -----------------------------------------------------------

    def _fix_document(
        self, group: Optional[str], label: str, url: str
    ) -> tuple[Optional[str], str, str]:
        """(group, label, filename-to-test) as the base should see them.

        The third value stands in for the URL only while the base decides
        what the document is; the real URL is what gets emitted. A shire
        overrides this for its own misfilings and calls up for the rest.
        """
        if url in self.relabelled_documents:
            return None, self.relabelled_documents[url], url
        return group, label, url

    def _pick_documents(self, links):
        real = {}
        fixed = []
        for group, label, url in links:
            group, label, stand_in = self._fix_document(group, label, url)
            real[stand_in] = url
            fixed.append((group, label, stand_in))
        agenda_url, minutes_url = super()._pick_documents(fixed)
        return real.get(agenda_url, agenda_url), real.get(minutes_url, minutes_url)
