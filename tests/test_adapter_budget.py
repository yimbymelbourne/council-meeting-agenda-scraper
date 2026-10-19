"""main.py's adapter time budget and dispatch order.

council-alerts SIGKILLs the adapter at 600 s and a kill discards stdout, so
before the budget one stuck council cost every council its update. The
budget has to do three things to prevent that, and each is tested here at
the boundary council-alerts actually sees: report the stragglers as
`Timeout` failures, keep stdout one valid JSON document, and exit 0 without
waiting for threads that will never return.
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time

from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.main import _dispatch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _FakeScraper(BaseScraper):
    def __init__(self, slug, expected_seconds, behaviour):
        self.expected_seconds = expected_seconds
        self._behaviour = behaviour
        super().__init__(slug, "VIC", "https://example.org")

    def scraper(self):
        self._behaviour(self)
        return [
            ScraperReturn(
                name="Ordinary Council Meeting",
                date="2026-03-12",
                time="7:00 PM",
                webpage_url="https://example.org/meetings",
                agenda_url="https://example.org/agenda.pdf",
            )
        ]


def test_slowest_scrapers_are_dispatched_first():
    """With one worker, start order is submission order."""
    started = []
    record = lambda s: started.append(s.council_name)
    scrapers = [
        _FakeScraper("cheap", 5, record),
        _FakeScraper("slowest", 97, record),
        _FakeScraper("slow", 30, record),
        _FakeScraper("also_cheap", 5, record),
    ]

    results, finished = _dispatch(scrapers, 1, None, adapter_mode=True)

    assert finished
    # Ties keep registry order, so cheap still precedes also_cheap.
    assert started == ["slowest", "slow", "cheap", "also_cheap"]
    assert all(r["ok"] for r in results)


def test_unfinished_scrapers_are_reported_as_timeouts():
    release = threading.Event()
    block = lambda s: release.wait(10)
    scrapers = [
        _FakeScraper("stuck", 100, block),
        _FakeScraper("queued", 1, lambda s: None),
    ]

    try:
        results, finished = _dispatch(scrapers, 1, 0.5, adapter_mode=True)
    finally:
        release.set()

    assert not finished
    by_council = {r["council"]: r for r in results}

    stuck = by_council["stuck"]
    assert stuck["ok"] is False
    assert stuck["error"]["type"] == "Timeout"
    assert stuck["elapsed_s"] >= 0.4

    # Never got a worker, so it has no running time to report.
    queued = by_council["queued"]
    assert queued["error"]["type"] == "Timeout"
    assert queued["error"]["message"].startswith("Never started")
    assert queued["elapsed_s"] is None


_ADAPTER_WITH_A_STUCK_COUNCIL = textwrap.dedent(
    """
    import sys, threading, time
    from aus_council_scrapers import main
    from aus_council_scrapers.base import SCRAPER_REGISTRY, BaseScraper, ScraperReturn

    class Stuck(BaseScraper):
        expected_seconds = 100
        def __init__(self):
            super().__init__("stuck_council", "VIC", "https://example.org")
        def scraper(self):
            # A thread that keeps printing after it is abandoned: its output
            # must not end up interleaved with the JSON on stdout.
            while True:
                print("stray output from an abandoned scraper")
                time.sleep(0.05)

    class Quick(BaseScraper):
        def __init__(self):
            super().__init__("quick_council", "NSW", "https://example.org")
        def scraper(self):
            return [ScraperReturn(
                name="Ordinary Council Meeting", date="2026-03-12", time=None,
                webpage_url="https://example.org/meetings",
                agenda_url="https://example.org/agenda.pdf",
            )]

    SCRAPER_REGISTRY.clear()
    SCRAPER_REGISTRY["Stuck"] = Stuck()
    SCRAPER_REGISTRY["Quick"] = Quick()
    sys.argv = ["main.py", "--adapter", "--format", "json"]
    main.main()
    """
)


def _assert_council_alerts_accepts(result: dict) -> None:
    """The parts of council-alerts' CouncilResultSchema (zod) that can fail.

    packages/scraper-adapter/src/schema.ts: council, state and ok are
    required; an ok:false result needs error.type and error.message as
    strings. One invalid result rejects the whole payload.
    """
    assert isinstance(result["council"], str)
    assert isinstance(result["state"], str)
    if result["ok"]:
        assert isinstance(result["meetings"], list)
    else:
        assert isinstance(result["error"]["type"], str)
        assert isinstance(result["error"]["message"], str)


def test_adapter_exits_cleanly_with_a_council_still_running(tmp_path):
    env = {**os.environ, "ADAPTER_BUDGET_S": "2", "PYTHONPATH": REPO_ROOT}

    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", _ADAPTER_WITH_A_STUCK_COUNCIL],
        cwd=tmp_path,  # main.py writes logs/ relative to the working directory
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - started

    # Before the budget this never returned: the executor joined a thread
    # that loops forever, and only the subprocess timeout above ended it.
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert elapsed < 45

    payload = json.loads(proc.stdout)
    by_council = {r["council"]: r for r in payload["results"]}
    for result in payload["results"]:
        _assert_council_alerts_accepts(result)

    assert by_council["stuck_council"]["error"]["type"] == "Timeout"
    quick = by_council["quick_council"]
    assert quick["ok"] is True
    assert len(quick["meetings"]) == 1
    assert isinstance(quick["elapsed_s"], float)
