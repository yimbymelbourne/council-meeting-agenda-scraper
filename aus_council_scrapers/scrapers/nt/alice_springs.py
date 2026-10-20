import datetime
import re
from typing import Optional

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectArchive
from aus_council_scrapers.resolve import ResolveScraper, SoleSourceFailed

SITE = "https://www.alicesprings.nt.gov.au"

# The last year the CouncilConnect module lists: its /council-meetings/past
# index runs 2020 to 2025 (checked 20 Oct 2026).
LAST_ARCHIVE_YEAR = 2025


@register_scraper
class AliceSpringsScraper(ResolveScraper):
    # The Town Council moved its Ordinary meetings to Resolve in early 2025.
    # The tenant's first event, 25 February 2025, is unpublished; its first
    # with papers is 25 March 2025. The 25 February agenda and minutes are in
    # the CouncilConnect module the site still serves at
    # /council-meetings/past/<year>, beside everything from 2020 on, so the
    # module is read for Council meetings before 25 March 2025. Its copy of
    # the 25 March meeting has the agenda alone; the tenant's has the minutes
    # too. Production asks for a year that is all Resolve, so the module
    # costs it nothing.
    tenant = "alicesprings"
    resolve_from = datetime.date(2025, 3, 25)

    # Every event the tenant has is an Ordinary Council meeting. The pattern
    # still names the type, so a committee the council starts publishing
    # there cannot add a request per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^Council Meeting$")
    # Named as the module names the same meetings, so a meeting type reads
    # the same either side of the move.
    meeting_type_names = {"Council Meeting": "Ordinary Council Meeting"}

    def __init__(self):
        super().__init__("alice_springs", "NT")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # Two reads with different stakes, each in its own try, so that one
        # failing cannot take the other's meetings with it.
        results: list[ScraperReturn] = []
        moved_failure: Optional[Exception] = None
        before = self.before_resolve(wanted)
        if before:
            try:
                results += self._archive(_MOVED_TYPES).read(
                    set(before), before=self.resolve_from
                )
            except Exception as error:
                # Council meetings, which moved. Decided below, once the
                # other read is in.
                moved_failure = error
                self.logger.warning(
                    f"{self.council_name}: could not read the CouncilConnect "
                    f"archive of Council meetings for {before}: "
                    f"{type(error).__name__}: {error}"
                )

        # Bodies the tenant has no type for, so the module is their only
        # record, until it stops in 2025. Neither need have met in a given
        # year, so finding none is not a failure. A failed fetch is: no other
        # source carries these meetings, so the council fails rather than
        # report success without them.
        archived = {year for year in wanted if year <= LAST_ARCHIVE_YEAR}
        if archived:
            try:
                results += self._archive(_UNMOVED_TYPES).read(
                    archived, allow_empty=True
                )
            except Exception as error:
                raise SoleSourceFailed(
                    f"{self.council_name}: could not read the CouncilConnect "
                    f"listings of {sorted(_UNMOVED_TYPES.values())}, the only "
                    f"source for those bodies: {type(error).__name__}: {error}"
                ) from error

        if moved_failure:
            # A year wholly before the move has no Council meeting on Resolve,
            # so the module was their only source and the council fails, as
            # for the bodies above. For 2025 alone, which Resolve carries from
            # 25 March, the loss of January and February is a warning, as in
            # `ResolveScraper.scraper`, unless nothing else was read.
            sole = [year for year in before if year < self.resolve_from.year]
            if sole:
                raise SoleSourceFailed(
                    f"{self.council_name}: could not read the CouncilConnect "
                    f"archive, the only source of Council meetings in {sole}: "
                    f"{type(moved_failure).__name__}: {moved_failure}"
                ) from moved_failure
            if not results:
                raise moved_failure
        return results

    def _archive(self, meeting_types: dict[str, str]) -> CouncilConnectArchive:
        # The module's time field is not when the meeting started: every
        # timed entry, January 2024 to April 2025, says 6:00 PM, and not one
        # of their 20 agendas agrees (the Ordinary meetings say 8.30AM and
        # 11.00AM or 9 am, the special ones 4 pm to 7:15pm; read 20 Oct
        # 2026). Earlier entries have no time. So no archive meeting carries
        # one.
        return CouncilConnectArchive(
            self, SITE, meeting_types, untimed_before=datetime.date.max
        )


# Council meetings, which moved to Resolve. The module's per-type listings
# are read, since its all-types listing is mostly advisory committees.
_MOVED_TYPES = {
    "ordinary-council-meeting": "Ordinary Council Meeting",
    "special-council-meeting": "Special Council Meeting",
}
# Bodies that did not move. The Special Confidential Meeting is a special
# Council meeting held in confidence, whose agenda is still published (2
# April 2025 is the last); the Development Committee, a planning body, is
# last listed in 2022. Left out are the advisory committees and the plain
# "Committee Meeting" type; each kept meeting costs a request.
_UNMOVED_TYPES = {
    "special-confidential-meeting": "Special Confidential Meeting",
    "development-committee-meeting": "Development Committee Meeting",
}
