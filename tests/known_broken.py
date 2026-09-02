"""Scrapers that are known to be broken, and in which way.

Entries are applied as **strict** xfails: if one starts passing, the build
fails until it is removed. Debt recorded here cannot quietly outlive the fix,
and it cannot be used to silence a new failure — a scraper that breaks in a
way not described here still goes red.

This is not the per-council "capability flag" idea that was rejected earlier.
That would have been an unfalsifiable claim about a council ("this one
publishes no minutes") that nothing could ever disprove. These are claims
about our own code, they are re-checked every run, and the list is meant to
shrink to nothing.

Two kinds, because a scraper can be broken in one way and fine in the other:

`REPLAY_BROKEN`
    Cannot reproduce its cassette — usually the cassette is empty or stale
    because the council's site moved. Fails `scraper_test`.

`OUTPUT_BROKEN`
    Produces output that violates the invariants — no meetings, unparseable
    dates, duplicates. Fails `test_conformance`.
"""

_PLATFORM_GONE = "{host} returns 404 — council has left the InfoCouncil platform"

REPLAY_BROKEN = {
    "hunters_hill": _PLATFORM_GONE.format(host="huntershill.infocouncil.biz"),
    "woollahra": _PLATFORM_GONE.format(host="woollahra.infocouncil.biz"),
}

OUTPUT_BROKEN = {
    "hunters_hill": _PLATFORM_GONE.format(host="huntershill.infocouncil.biz"),
    "woollahra": _PLATFORM_GONE.format(host="woollahra.infocouncil.biz"),
}
