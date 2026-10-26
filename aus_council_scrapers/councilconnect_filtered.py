"""CouncilConnect councils read through the all-types year listing, filtered.

`CouncilConnectScraper.meeting_types` limits a council to some meeting types
by reading each type's own year page, /council-meetings/<type>/past/<year>.
On some sites those pages cannot be trusted, and nothing on them says so:

- **Missing meetings.** Dalwallinu's /ordinary-council-meeting/past/2026
  lists 3 of the 8 Ordinary meetings that /council-meetings/past/2026 lists,
  as a normal 200 page (20 Oct 2026). Its 2020 and 2022 type pages each drop
  one meeting as well.
- **No type pages at all.** Every type page at Beverley is a 404, for every
  year, and so is Chapman Valley's for its Regional Development Assessment
  Panel, though the panel's meetings are on the all-types listing.
- **Types that last a year.** Ravensthorpe filed its 2020 Ordinary meetings
  under a type called "Ordinary Council Meeting - 2020", and two 2021 ones
  under "... - 2021". As type pages, each would cost a request every night
  for a year that never changes.

So this reads the one listing every site has, /council-meetings/past/<year>,
and keeps the `meeting_types` from it before any meeting page is fetched. A
skipped meeting costs nothing: the listing names each meeting's type in its
URL. A year listing is one request per ten meetings of every type, which for
the small councils that use this is two or three pages a year—no more than
the type pages it replaces.

What `meeting_types` still does in the base is unchanged: it supplies the
type names, it filters the upcoming page the same way, and it turns on the
heading test that drops forums and committees filed under a Council type.

Six clean-ups ride along, each seen on a council here and each a change
the base could take for everyone:

- **Cancelled meetings.** Tiwi Islands keeps a page for its cancelled 23
  April 2025 meeting ("Ordinary Council Meeting CANCELLED"), with the agenda
  of the 16 April meeting it replaced on it. A listing entry headed as
  cancelled is skipped before its page is fetched.
- **Cancellation notices.** Exmouth files the public notice cancelling its
  26 March 2026 Ordinary meeting under that meeting's "Agenda" heading. A
  document whose label or filename says "cancel" is never an agenda or
  minutes.
- **An agenda that includes its late item.** The base drops anything that
  mentions a late item, which is right for the late item itself. But
  Ravensthorpe's only agenda for 16 June 2026 is "Agenda OCM 16.06.2026 -
  Final v2 Inc Late Item". Where nothing else is the agenda, a document
  whose label starts by calling itself the agenda and says it *includes*
  the late items is taken.
- **Month-first headings.** Merredin and Ravensthorpe head meetings
  "September Ordinary Council Meeting". The base matches a heading to its
  type by similarity, and the month tips some over the line and not others
  ("May" passes, "September" does not), so a leading month name is dropped
  before that test. And a heading whose words are all in its type's name
  ("Special Meeting" under "Special Council Meeting") takes the type's.
- **Packets worded another way.** "Agenda & Attachments", "Attachments
  Included" and "Inline Attachments" are each a meeting's only agenda at
  Coolgardie, Ravensthorpe and Chapman Valley, and Exmouth once wrote "and
  Attachment_"; the base reads all of them as attachments. They are read as
  packets, but only where the base found no
  agenda or minutes, so a bare document posted beside one still wins.
- **An agenda filed as an attachment.** Merredin has twice put the agenda
  under its Attachments heading, which the base never reads. Where nothing
  else is the agenda, the one link there whose label starts "Agenda" is.

This belongs in `CouncilConnectScraper` as an option, and is kept apart only
because the base module is shared by work in flight.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlparse

from aus_council_scrapers.base import ScraperReturn
from aus_council_scrapers.councilconnect import (
    _NOT_THE_MEETINGS,
    _NOT_THE_MEETINGS_FILE,
    CouncilConnectScraper,
)

_CANCELLED = re.compile(r"cancel", re.IGNORECASE)
# "Agenda OCM 16.06.2026 - Final v2 Inc Late Item": an agenda first, which
# says it includes the late items, as opposed to a late item on its own.
_AGENDA_WITH_LATE_ITEMS = re.compile(
    r"^\s*(?:final\s+)?agenda\b.*\binc(?:l(?:uding|udes)?)?\.?\s+late\s+items?\b",
    re.IGNORECASE,
)
_ATTACHMENT = re.compile(r"attach", re.IGNORECASE)
# Packets the base's packet test does not recognise, because the word
# before "attachments" is not one it knows: Coolgardie's "OCM Agenda &
# Attachments 27 April 2021", Ravensthorpe's "Agenda - Special Council
# Meeting - 31 October 2023 - Attachments Included", Chapman Valley's
# "Special Council Meeting Agenda - February 2024 - Inline Attachments".
# Each is the meeting's only agenda. They are reworded to the "with
# attachments" form the base already reads as a packet.
#
# Exmouth's 2 February 2023 special meeting has "Special Council Meeting
# Agenda and Attachment_ 2 February 2023" and "... Minutes and Attachment_
# ...". The base's packet test ends on \b, and "_" is a word character, so
# "Attachment_" never ends a word there and both were dropped as
# attachments. The underscore is taken in with the match.
_OTHER_PACKET = re.compile(
    r"&\s*attachments?\b|\battachments?\s+included\b|\binline\s+attachments?\b"
    r"|\b(?:with|and|incl\w*)[\s(-]+(?:all[\s-]+)?attachments?_+",
    re.IGNORECASE,
)
# An agenda filed under a meeting's Attachments heading, which the base
# never reads: Merredin's "Agenda - Special Council Meeting - 28 July 2020"
# and "Agenda - 18 May 2021" are the only agendas on those pages. The
# attachments there are labelled as such ("Attachment 7.1A - Minutes -
# ..."), so a label that starts by calling itself the agenda is not one.
_STARTS_AS_AGENDA = re.compile(r"^\s*agenda\b", re.IGNORECASE)
_LEADING_MONTH = re.compile(
    r"^\s*(?:january|february|march|april|may|june|july|august|september"
    r"|october|november|december)\s+(?=\w)",
    re.IGNORECASE,
)


_ODD_MINUTES = re.compile(r":(?!00|15|30|45)\d\d")


class FilteredListingCouncilConnectScraper(CouncilConnectScraper):
    """A `CouncilConnectScraper` that reads the all-types listing and keeps
    only `meeting_types`, which a subclass must set.

    `corrected_dates`
        `{meeting page url: (ISO date, why)}` for a meeting whose date field
        is wrong, checked by reading its papers. Like `wrong_documents`, each
        entry is a case whose documents were read, not a filename guess.
    """

    corrected_dates: dict[str, tuple[str, str]] = {}

    def _listing_urls(self, year: int) -> list[str]:
        return [f"{self.base_url}/council-meetings/past/{year}"]

    def _read_meeting(self, url, labels, fallback) -> Optional[ScraperReturn]:
        # Both the year listings and the upcoming page come through here
        # before a meeting's page is fetched, so this is the one place that
        # decides which types cost a request. The upcoming page is already
        # filtered by the base; the year listings are not.
        if self.meeting_type_of(url) not in self.meeting_types:
            return None
        return super()._read_meeting(url, labels, fallback)

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is None:
            return None
        if url in self.corrected_dates:
            meeting.date = self.corrected_dates[url][0]
        # The date field is sometimes the moment the meeting was entered,
        # not when it sits: Boddington's February 2024 meeting reads "Friday,
        # February 23, 2024 - 03:27 PM", Chapman Valley's "11:49 AM", and
        # Dalwallinu's "12:00 AM", a time never filled in. Meetings here
        # start on the quarter hour, so a time that does not is a stamp and
        # is left blank rather than passed on as the meeting's.
        if meeting.time and (
            meeting.time == "12:00 AM" or _ODD_MINUTES.search(meeting.time)
        ):
            meeting.time = None
        return meeting

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        heading = summary.find(["h2", "h3"])
        if heading and _CANCELLED.search(heading.get_text(" ", strip=True)):
            return []
        return super()._summary_meeting(summary, listing_url, labels, year, seen)

    def _pick_documents(self, links, meeting_name=None, date=None):
        def filename(url):
            return unquote(urlparse(url).path.rsplit("/", 1)[-1])

        links = [
            (group, label, url)
            for group, label, url in links
            if not _CANCELLED.search(f"{label} {filename(url)}")
            and url not in self.wrong_documents
            and urlparse(url).path.lower().endswith(".pdf")
        ]
        agenda_url, minutes_url = super()._pick_documents(links)
        # The packets the base cannot see are read only where it found
        # nothing: Chapman Valley posts its August 2024 minutes both bare
        # and "Inline Attachments", and the bare one should stay first.
        if agenda_url is None or minutes_url is None:
            packet_agenda, packet_minutes = super()._pick_documents(
                [
                    (group, _OTHER_PACKET.sub("with attachments ", label), url)
                    for group, label, url in links
                ]
            )
            agenda_url = agenda_url or packet_agenda
            minutes_url = minutes_url or packet_minutes
        if agenda_url is None:
            agenda_url = next(
                (
                    url
                    for group, label, url in links
                    if _AGENDA_WITH_LATE_ITEMS.search(label)
                    and not _ATTACHMENT.search(f"{group or ''} {label}")
                ),
                None,
            )
        if agenda_url is None:
            filed_as_attachments = [
                url
                for group, label, url in links
                if group
                and _ATTACHMENT.search(group)
                and _STARTS_AS_AGENDA.search(label)
                and not _NOT_THE_MEETINGS.search(label)
                and not _NOT_THE_MEETINGS_FILE.search(filename(url).replace("_", " "))
            ]
            # One, or nothing says which.
            if len(filed_as_attachments) == 1:
                agenda_url = filed_as_attachments[0]
        return agenda_url, minutes_url

    def _name(self, heading, type_slug, labels):
        name = super()._name(_LEADING_MONTH.sub("", heading or ""), type_slug, labels)
        # "Special Meeting" filed under "Special Council Meeting" (Coolgardie
        # 13 July 2021, Tiwi Islands 2023) is that type with a word left
        # out, and too short beside it for the base's similarity test. A
        # heading whose words are all in the type's name takes the type's.
        # Ravensthorpe's "Special Meeting" filed under its Ordinary type
        # keeps its own name: "special" is not in "Ordinary Council Meeting".
        label = labels.get(type_slug) if type_slug else None
        if label and set(name.lower().split()) < set(label.lower().split()):
            return label
        return name
