"""How we describe ourselves, and the shape of the exceptions.

The decision recorded in #142 is that the requests channel identifies itself
rather than imitating a browser. The value of that decision is entirely in it
being the *default*, so these tests guard the default and constrain what an
exception is allowed to look like — a council-specific override, not a quiet
return to spoofing everywhere.
"""

import pytest

from aus_council_scrapers.base import (
    BROWSER_USER_AGENT,
    IDENTIFYING_USER_AGENT,
    SCRAPER_REGISTRY,
    BaseScraper,
    BlockedByWAF,
    DefaultFetcher,
    resolve_user_agent,
)


def test_default_identifies_us_with_a_contact_url():
    assert IDENTIFYING_USER_AGENT.startswith("aus-council-scrapers/")
    assert "github.com/yimbymelbourne" in IDENTIFYING_USER_AGENT
    assert "Mozilla" not in IDENTIFYING_USER_AGENT
    assert DefaultFetcher.DEFAULTHEADERS["User-Agent"] == IDENTIFYING_USER_AGENT


def test_browser_string_is_a_real_chrome_string():
    """The old one ended `Safari/537.3`, which no browser sends.

    A one-digit-short token is a stable, unusual fingerprint — the opposite of
    what a disguise is for.
    """
    assert BROWSER_USER_AGENT.endswith("Safari/537.36")
    assert "AppleWebKit/537.36" in BROWSER_USER_AGENT


def test_precedence_override_then_env_then_default(monkeypatch):
    monkeypatch.delenv("USER_AGENT", raising=False)
    assert resolve_user_agent() == IDENTIFYING_USER_AGENT

    monkeypatch.setenv("USER_AGENT", "from-env/1.0")
    assert resolve_user_agent() == "from-env/1.0"

    # A scraper's override outranks the environment: it is there because that
    # council refuses anything else, so a global env var must not undo it.
    assert resolve_user_agent("override/1.0") == "override/1.0"


def test_env_var_reaches_the_session(monkeypatch):
    monkeypatch.setenv("USER_AGENT", "from-env/1.0")
    fetcher = DefaultFetcher(fetch_delay=0)
    assert fetcher.user_agent == "from-env/1.0"


def test_scraper_overrides_are_the_browser_string_only():
    """An override may only be the vetted browser string.

    Any other value would be a council-specific invention with no measurement
    behind it, and the whole point of routing these through one constant is
    that there is exactly one thing to re-verify when it stops working.
    """
    overrides = {
        slug: scraper.user_agent
        for slug, scraper in SCRAPER_REGISTRY.items()
        if scraper.user_agent is not None
    }
    assert all(value == BROWSER_USER_AGENT for value in overrides.values()), overrides


def test_manningham_keeps_its_override():
    """Measured 2026-08-20: 200 as a browser, 403 when identifying.

    If this council changes its mind, delete the override and this test —
    do not leave an unexplained spoof in place.
    """
    manningham = SCRAPER_REGISTRY["ManninghamScraper"]
    assert manningham.user_agent == BROWSER_USER_AGENT
    assert manningham.fetcher.user_agent == BROWSER_USER_AGENT


def test_stripping_the_headless_marker_stays_opt_in():
    """Off by default, because it is not a free improvement.

    Measured 2026-08-20 by running each Selenium-channel scraper both ways:
    melbourne needs it (0 meetings without, 224 with) and banyule is broken by
    it (73 meetings without, 10 with — its year-filter postbacks stop
    working). campbelltown, darebin and strathfield are indifferent. A global
    default would therefore trade one council for another.
    """
    assert BaseScraper.strip_headless_user_agent is False
    assert not DefaultFetcher(fetch_delay=0).strip_headless_user_agent

    opted_in = {
        slug
        for slug, scraper in SCRAPER_REGISTRY.items()
        if scraper.strip_headless_user_agent
    }
    assert opted_in == {"MelbourneScraper"}, opted_in
    assert SCRAPER_REGISTRY["BanyuleScraper"].strip_headless_user_agent is False


def test_blocked_message_names_what_we_sent_and_what_to_try():
    identifying = BlockedByWAF("https://example.gov.au", IDENTIFYING_USER_AGENT)
    assert IDENTIFYING_USER_AGENT in str(identifying)
    assert "BROWSER_USER_AGENT" in str(identifying)

    # Already a browser: sending yet another header is not the answer.
    as_browser = BlockedByWAF("https://example.gov.au", BROWSER_USER_AGENT)
    assert "not a User-Agent problem" in str(as_browser)
    assert "Selenium" in str(as_browser)
