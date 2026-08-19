"""Record/replay fixtures for scraper tests.

A cassette is a JSON list of ``[key, value]`` pairs recorded in call order.
Keys are small JSON arrays whose first element names the channel:

    ["requests", url, method]                  # no extra request kwargs
    ["requests", url, method, kwargs_json]     # params/data/json/headers etc.
    ["selenium", url]                          # fetch_with_selenium
    ["driver", n, op, args]                    # nth direct WebDriver call

Playback is **strict**: any call that was not recorded raises `CassetteMiss`
rather than returning a plausible-looking empty page. A scraper that starts
requesting a URL it did not request when the cassette was cut has changed
behaviour, and the test must say so instead of silently finding fewer
meetings.
"""

from __future__ import annotations

import json
import os
from typing import Any

from aus_council_scrapers.base import Fetcher


class CassetteMiss(BaseException):
    """A call was made that the cassette has no recording for.

    Deliberately derived from `BaseException`, not `Exception`, so that the
    broad ``except Exception`` blocks scrapers use to tolerate flaky councils
    cannot swallow a missing recording and quietly return fewer meetings.
    """

    def __init__(self, description: str, slug: str | None = None):
        hint = (
            f"\n\nRe-record with:  RECORD={slug} poetry run pytest tests/scraper_test.py -k {slug}"
            if slug
            else "\n\nRe-record this scraper's cassette with RECORD=<slug>."
        )
        super().__init__(description + hint)


class UnsupportedDriverCall(BaseException):
    """A WebDriver method was used that cannot be recorded or replayed.

    Also outside the `Exception` hierarchy, for the same reason as
    `CassetteMiss`.
    """


def _canonical_kwargs(kwargs: dict[str, Any]) -> str:
    """Stable string form of request kwargs, so keys compare reliably."""
    return json.dumps(kwargs, sort_keys=True, default=str)


def requests_key(url: str, method: str, kwargs: dict[str, Any] | None) -> list:
    # Omit the kwargs slot entirely when there are none, so keys stay
    # identical to those in cassettes recorded before kwargs were supported.
    if not kwargs:
        return ["requests", url, method]
    return ["requests", url, method, _canonical_kwargs(kwargs)]


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


class RecordingDriver:
    """Wraps a real WebDriver and records the calls a scraper makes.

    Only the subset of the WebDriver API that can be faithfully replayed is
    allowed. `find_element` and friends return live element handles that
    cannot be serialised, so they raise at record time — driving the page
    through `execute_script` keeps the scraper replayable.
    """

    def __init__(self, driver, replay_data: list):
        self._driver = driver
        self._replay_data = replay_data
        self._n = 0

    def _record(self, op: str, args: str, value):
        self._replay_data.append([["driver", self._n, op, args], value])
        self._n += 1
        return value

    @property
    def page_source(self) -> str:
        return self._record("page_source", "", self._driver.page_source)

    def execute_script(self, script: str, *args):
        result = self._driver.execute_script(script, *args)
        # The return value is discarded: scrapers use execute_script to drive
        # the page, then read the result back through page_source.
        self._record("execute_script", script, None)
        return result

    def get(self, url: str):
        self._driver.get(url)
        self._record("get", url, None)

    def __getattr__(self, name):
        raise UnsupportedDriverCall(
            f"driver.{name} cannot be recorded for replay. Drive the page with "
            f"execute_script() and read it back via page_source, or fetch it "
            f"with fetch_with_requests()/fetch_with_selenium()."
        )


class RecordingFetcher(Fetcher):
    def __init__(self, delegated_fetcher: Fetcher):
        self.replay_data: list = []
        self.__delegate = delegated_fetcher
        self.__driver: RecordingDriver | None = None

    def get_selenium_driver(self):
        if self.__driver is None:
            self.__driver = RecordingDriver(
                self.__delegate.get_selenium_driver(), self.replay_data
            )
        return self.__driver

    def fetch_with_requests(self, url, method="GET", **kwargs):
        result = self.__delegate.fetch_with_requests(url, method, **kwargs)
        self.replay_data.append([requests_key(url, method, kwargs), result])
        return result

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        result = self.__delegate.fetch_with_selenium(url, wait_time, wait_condition)
        self.replay_data.append([["selenium", url], result])
        return result

    def close(self):
        self.__delegate.close()


# --------------------------------------------------------------------------
# Playback
# --------------------------------------------------------------------------


class PlaybackDriver:
    """Replays recorded WebDriver calls in the order they were recorded."""

    def __init__(self, ops: list, slug: str | None = None):
        self._ops = ops
        self._slug = slug
        self._n = 0

    def _next(self, op: str, args: str):
        if self._n >= len(self._ops):
            raise CassetteMiss(
                f"Scraper made more WebDriver calls than were recorded "
                f"({self._n + 1} > {len(self._ops)}); next was {op}({args!r}).",
                self._slug,
            )
        recorded_op, recorded_args, value = self._ops[self._n]
        if recorded_op != op or recorded_args != args:
            raise CassetteMiss(
                f"WebDriver call {self._n} does not match the recording.\n"
                f"  recorded: {recorded_op}({recorded_args!r})\n"
                f"  called:   {op}({args!r})",
                self._slug,
            )
        self._n += 1
        return value

    @property
    def page_source(self) -> str:
        return self._next("page_source", "")

    def execute_script(self, script: str, *args):
        return self._next("execute_script", script)

    def get(self, url: str):
        return self._next("get", url)

    def __getattr__(self, name):
        raise UnsupportedDriverCall(
            f"driver.{name} is not replayable; it was never recorded."
        )


class PlaybackFetcher(Fetcher):
    def __init__(self, replay_data: list, slug: str | None = None):
        self._slug = slug
        self._responses: dict[tuple, str] = {}
        driver_ops: list[tuple[int, str, str, Any]] = []

        for key, value in replay_data:
            if key and key[0] == "driver":
                _, index, op, args = key
                driver_ops.append((index, op, args, value))
            else:
                self._responses[tuple(key)] = value

        driver_ops.sort(key=lambda op: op[0])
        self._driver_ops = [(op, args, value) for _, op, args, value in driver_ops]

    def get_selenium_driver(self):
        return PlaybackDriver(self._driver_ops, self._slug)

    def sleep(self, seconds: float) -> None:
        # Nothing is actually loading during playback.
        return None

    def _lookup(self, key: tuple, description: str) -> str:
        if key in self._responses:
            return self._responses[key]
        raise CassetteMiss(
            f"No recorded response for {description}.\n"
            f"  looked up: {list(key)}\n"
            f"  cassette has {len(self._responses)} recorded response(s).",
            self._slug,
        )

    def fetch_with_requests(self, url, method="GET", **kwargs):
        key = tuple(requests_key(url, method, kwargs))
        return self._lookup(key, f"{method} {url}")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        return self._lookup(("selenium", url), f"selenium GET {url}")


# --------------------------------------------------------------------------
# Cassette files
# --------------------------------------------------------------------------

CASSETTE_DIR = os.path.join("tests", "test-cases")


def cassette_paths(slug: str) -> tuple[str, str]:
    """Return (result_path, replay_data_path) for a council slug."""
    return (
        os.path.join(CASSETTE_DIR, f"{slug}-result.json"),
        os.path.join(CASSETTE_DIR, f"{slug}-replay_data.json"),
    )


def should_record(slug: str) -> bool:
    """True when RECORD asks for this slug.

    ``RECORD=1`` (or ``all``) re-records everything in the current selection;
    ``RECORD=waverley,banyule`` re-records only those slugs. Scoping matters:
    a bare re-record of all 33 cassettes would sweep unrelated pending work
    into whatever branch happened to run it.
    """
    record = os.environ.get("RECORD", "").strip()
    if not record:
        return False
    if record in ("1", "all", "true"):
        return True
    return slug in {part.strip() for part in record.split(",") if part.strip()}
