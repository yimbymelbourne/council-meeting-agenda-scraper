#!/usr/bin/env python3
"""Identify which meeting platform a council runs, before writing a parser.

    python scripts/detect_platform.py knox            # a slug from docs/councils.md
    python scripts/detect_platform.py https://...     # or a URL directly
    python scripts/detect_platform.py --all           # every council without a scraper

Fetches through the project's own fetcher, so it is throttled per host and a
firewall block surfaces as the same deferral a scraper would hit.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests  # noqa: E402

from aus_council_scrapers.base import (  # noqa: E402
    BROWSER_USER_AGENT,
    USER_AGENT_ISSUE,
    BlockedByWAF,
    DefaultFetcher,
)
from aus_council_scrapers.platforms import (  # noqa: E402
    detect,
    is_js_challenge,
    platform_links,
)

COUNCILS_DOC = "docs/councils.md"


def councils_from_doc() -> list[tuple[str, str]]:
    """(slug, url) for every council listed, in document order."""
    rows = []
    for line in open(COUNCILS_DOC):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or not re.fullmatch(r"[a-z0-9_]+", cells[-1]):
            continue
        url = next((c for c in cells if c.startswith("http")), "")
        rows.append((cells[-1], url))
    return rows


def without_scrapers(rows):
    recorded = {
        os.path.basename(p).replace("-result.json", "")
        for p in glob.glob("tests/test-cases/*-result.json")
    }
    return [(slug, url) for slug, url in rows if slug not in recorded]


def classify(fetcher: DefaultFetcher, url: str) -> tuple[str, str]:
    """Return (verdict, detail) for one council URL."""
    try:
        html = fetcher.fetch_with_requests(url)
    except BlockedByWAF:
        # Two extra requests to tell three different blocks apart: a JS
        # challenge that needs a browser, a council that wants a browser-shaped
        # User-Agent, and a genuine refusal. Send the same headers the fetcher
        # does — a bare request triggers challenges that our real header set
        # passes, which would misreport a reachable council as blocked.
        try:
            head = requests.head(
                url,
                timeout=20,
                allow_redirects=True,
                headers=DefaultFetcher.DEFAULTHEADERS,
            )
            if is_js_challenge(head.headers):
                return "challenge", "needs Selenium — no User-Agent gets past this"
        except Exception:
            pass
        try:
            browser = requests.get(
                url,
                timeout=30,
                allow_redirects=True,
                headers={
                    **DefaultFetcher.DEFAULTHEADERS,
                    "User-Agent": BROWSER_USER_AGENT,
                },
            )
            if browser.status_code == 200:
                return (
                    "browser-only",
                    "200 with BROWSER_USER_AGENT — set `user_agent = "
                    "BROWSER_USER_AGENT` on the scraper, as manningham does",
                )
        except Exception:
            pass
        return "blocked", f"403 even when identifying honestly — see {USER_AGENT_ISSUE}"
    except Exception as e:
        return "error", f"{type(e).__name__}: {str(e)[:70]}"

    if not html.strip():
        # A 200/202 with nothing in it is an AWS WAF challenge, not a council
        # with an empty meetings page. Reporting it as "bespoke, 0 bytes" is
        # how `melbourne` read as unfinished rather than unreachable.
        try:
            head = requests.head(url, timeout=20, allow_redirects=True,
                                 headers=DefaultFetcher.DEFAULTHEADERS)
            if is_js_challenge(head.headers):
                return "challenge", (
                    "empty body behind a WAF challenge — needs Selenium, and "
                    "note it never raises because the status is not an error"
                )
        except Exception:
            pass
        return "empty", "fetched nothing — check the URL and the response headers"

    found = detect(html, url)
    if found:
        platform = found[0]
        detail = platform.guidance
        if platform.reference:
            detail += f" See {platform.reference}."
        return platform.name, detail

    links = platform_links(html)
    if links:
        return "links out", f"page links to {', '.join(sorted(links))} — try that URL"

    return "bespoke", f"no known platform ({len(html):,} bytes) — needs a parser"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", help="council slug or URL")
    parser.add_argument(
        "--all", action="store_true", help="every council without a scraper"
    )
    parser.add_argument(
        "--delay", type=float, default=2.5, help="seconds between requests per host"
    )
    args = parser.parse_args()

    fetcher = DefaultFetcher(fetch_delay=args.delay)

    if args.all:
        targets = without_scrapers(councils_from_doc())
    elif args.target and args.target.startswith("http"):
        targets = [(args.target, args.target)]
    elif args.target:
        by_slug = dict(councils_from_doc())
        if args.target not in by_slug:
            print(f"'{args.target}' is not in {COUNCILS_DOC}", file=sys.stderr)
            return 2
        targets = [(args.target, by_slug[args.target])]
    else:
        parser.error("give a slug, a URL, or --all")

    missing_url = [slug for slug, url in targets if not url]
    targets = [(slug, url) for slug, url in targets if url]

    print(f"{'council':22}{'platform':16}notes")
    print("-" * 100)
    for slug, url in targets:
        verdict, detail = classify(fetcher, url)
        print(f"{slug[:21]:22}{verdict:16}{detail}")

    if missing_url:
        print(
            f"\nNo meeting-page URL in {COUNCILS_DOC}, so nothing to check: "
            f"{', '.join(missing_url)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
