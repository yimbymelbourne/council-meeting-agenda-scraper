import argparse
from concurrent.futures import ThreadPoolExecutor, wait
import contextlib
import io
import json
import logging
import os.path
import sys
import time
from datetime import date, datetime
from typing import Optional

from dotenv import dotenv_values

import aus_council_scrapers.database as db
from aus_council_scrapers.base import SCRAPER_REGISTRY, BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.discord_bot import DiscordNotifier
from aus_council_scrapers.logging_config import setup_logging
from aus_council_scrapers.utils import (
    KeywordCounts,
    download_pdf,
    extract_keywords,
    format_date_for_message,
    read_pdf,
    send_email,
    write_email,
)

config = dotenv_values(".env")


def json_default(o):
    """Fallback serializer for objects that json can't handle (e.g. date/datetime)."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


@contextlib.contextmanager
def suppress_stdout(enabled: bool):
    """
    Guardrail: some scrapers still use print(). In JSON mode we must keep stdout clean.
    """
    if not enabled:
        yield
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def _matches(selector: str, value: str) -> bool:
    """Does `value` appear in a comma-separated `--council`/`--state` list?"""
    wanted = {part.strip().lower() for part in selector.split(",") if part.strip()}
    return value.lower() in wanted


# How long adapter mode waits for scrapers before giving up on the stragglers.
#
# council-alerts SIGKILLs this process at 600 s (SCRAPE_TIMEOUT_MS), and a
# kill discards stdout—so one stuck council used to cost every council its
# update that night. Stopping ourselves first turns that into losing only the
# councils that had not finished. 480 s leaves two minutes for what the
# budget does not cover: interpreter start-up and importing every scraper
# module (it is measured from dispatch), serialising the JSON, and Node
# reading it. `ADAPTER_BUDGET_S` overrides it from the workflow's `env:`
# block; keep it well under SCRAPE_TIMEOUT_MS.
DEFAULT_ADAPTER_BUDGET_S = 480.0


def _adapter_budget_s() -> float:
    return float(os.environ.get("ADAPTER_BUDGET_S", DEFAULT_ADAPTER_BUDGET_S))


def _failure(
    scraper: BaseScraper, error_type: str, message: str, elapsed_s: Optional[float]
) -> dict:
    """An ok:false result in the shape council-alerts' zod schema accepts.

    `council`, `state` and `error.{type,message}` are all required strings
    there. A result missing any of them fails validation for the *whole*
    payload, not just that council.
    """
    return {
        "ok": False,
        "council": scraper.council_name,
        "state": scraper.state.upper(),
        "error": {"type": error_type, "message": message},
        "elapsed_s": elapsed_s,
        "egress": scraper.egress,
    }


def _dispatch(
    scrapers: list[BaseScraper],
    workers: int,
    budget_s: Optional[float],
    **run_kwargs,
) -> tuple[list[dict], bool]:
    """Run scrapers on a thread pool, slowest first, for at most `budget_s`.

    Returns the results and whether every scraper finished. A council still
    running (or still queued) when the budget runs out is reported as
    ok:false with error type `Timeout`, which council-alerts records as a
    failed scrape while leaving that council's stored meetings alone.

    When anything is unfinished the pool is NOT joined: Python cannot kill a
    thread, so a worker blocked on a silent socket would hold the process
    open until the very SIGKILL this exists to avoid. The caller must write
    its output and leave with `_hard_exit`.

    Dispatch is longest-expected-first. Wall time is set by whichever
    scraper finishes last, and a 100 s scraper submitted after the cheap
    ones starts late and runs on alone; submitted first, it overlaps with
    everything else. The sort is stable, so ties keep registry order.
    """
    ordered = sorted(scrapers, key=lambda s: s.expected_seconds, reverse=True)
    started_at: dict[str, float] = {}

    def run(scraper: BaseScraper):
        started_at[scraper.council_name] = time.monotonic()
        return run_scraper(scraper, **run_kwargs)

    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(run, scraper): scraper for scraper in ordered}
    done, not_done = wait(futures, timeout=budget_s)

    def elapsed(scraper: BaseScraper) -> Optional[float]:
        start = started_at.get(scraper.council_name)
        return None if start is None else round(time.monotonic() - start, 1)

    results: list[dict] = []
    for future, scraper in futures.items():
        if future in done:
            try:
                out = future.result()
            except Exception as e:
                # run_scraper catches everything a scraper raises, so this is
                # a bug in run_scraper itself. Still report it per council:
                # the bare {"ok": False, "error": "<str>"} this used to emit
                # has no council or state and fails the zod schema, which
                # rejects the whole payload.
                logging.exception(f"Worker future failed unexpectedly: {e}")
                out = _failure(scraper, type(e).__name__, str(e), elapsed(scraper))
        else:
            future.cancel()
            seconds = elapsed(scraper)
            if seconds is None:
                message = (
                    f"Never started: the adapter's {budget_s:.0f} s budget ran "
                    f"out while it was queued behind slower councils."
                )
            else:
                message = (
                    f"Still running after {seconds:.0f} s when the adapter's "
                    f"{budget_s:.0f} s budget ran out; abandoned so the other "
                    f"councils' results are kept."
                )
            scraper.logger.error(message)
            out = _failure(scraper, "Timeout", message, seconds)

        if out is not None:
            results.append(out)

    if not_done:
        executor.shutdown(wait=False, cancel_futures=True)
    else:
        executor.shutdown(wait=True)
    return results, not not_done


def _write_json(stream, args, results: list[dict]) -> None:
    payload = {
        "format_version": 1,
        "adapter_mode": args.adapter,
        "council_filter": args.council,
        "state_filter": args.state,
        "years_filter": args.years,
        "results": results,
    }
    stream.write(json.dumps(payload, ensure_ascii=False, default=json_default))
    stream.write("\n")
    stream.flush()


def _hard_exit() -> None:
    """Exit now, without waiting for worker threads that will never return.

    `os._exit` skips every flush, so flush first. Exit 0, not 1:
    council-alerts rejects the whole payload when the exit code is non-zero,
    and the councils that timed out are already reported inside it.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    for handler in logging.getLogger().handlers:
        handler.flush()
    os._exit(0)


def main():

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", help="Force re-scrape", action="store_true")
    parser.add_argument(
        "--skip-keywords", help="Skip keyword extraction", action="store_true"
    )
    parser.add_argument(
        "--council", help="Scan only these councils (comma-separated)"
    )
    parser.add_argument("--state", help="Scan only these states (comma-separated)")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Filter meetings by year(s). Example: --years 2025 or --years 2024 2025",
    )
    parser.add_argument("--log-level", help="Set the log level", default="INFO")
    # 10, up from 6. council-alerts passes no --workers flag, so this default
    # is production's concurrency. More workers used to mean more
    # simultaneous requests to any vendor host several councils share,
    # because each scraper throttled only itself. DefaultFetcher now spaces
    # requests per host across the whole process, so extra workers add
    # parallelism across hosts without adding load on any one of them.
    parser.add_argument("--workers", help="Number of workers", default=10, type=int)
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format. Use json for machine-readable adapter output.",
    )
    parser.add_argument(
        "--adapter",
        action="store_true",
        help="Adapter mode: disable DB writes, notifications, and file side effects.",
    )
    parser.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Skip PDF download/keyword extraction (useful for adapter mode).",
    )
    args = parser.parse_args()

    # Validate years argument
    if args.years:
        current_year = datetime.now().year
        min_year = EARLIEST_YEAR
        max_year = current_year + 2
        for year in args.years:
            if year < min_year or year > max_year:
                parser.error(
                    f"Year {year} is outside valid range {min_year}-{max_year}. "
                    f"Scrapers only fetch data from {min_year} to {max_year} (current year + 2)."
                )

    # Adapter defaults (safe, non-side-effecting)
    if args.adapter:
        args.skip_keywords = True
        args.skip_pdf = True

    # Setup logging
    setup_logging(level=args.log_level.upper())
    logging.info("YIMBY SCRAPER Started")
    start_time = time.time()

    # DB is legacy-mode only
    if not args.adapter:
        if args.fresh:
            try:
                os.remove("./agendas.db")
            except FileNotFoundError:
                pass

        if not os.path.exists("./agendas.db"):
            db.init()

    # Captured before stdout is redirected, so the timeout path can write the
    # payload to the real stream from inside the redirect.
    real_stdout = sys.stdout

    # In JSON mode, suppress any accidental prints from scrapers
    with suppress_stdout(args.format == "json"):
        # Filter by council and state. Both accept a comma-separated list,
        # because our only production caller already sends one:
        # council-alerts builds `--council a,b` from its workflow input, and
        # an exact single-name comparison matched nothing, so a
        # multi-council request scraped no councils at all and reported
        # success with an empty result.
        selected = [
            scraper
            for scraper in SCRAPER_REGISTRY.values()
            if (not args.state or _matches(args.state, scraper.state))
            and (not args.council or _matches(args.council, scraper.council_name))
        ]

        # The budget guards the production SIGKILL, so it applies only in
        # adapter mode. Legacy mode writes to SQLite, and abandoning a thread
        # mid-write there is worse than waiting.
        budget_s = _adapter_budget_s() if args.adapter else None
        results, finished = _dispatch(
            selected,
            args.workers,
            budget_s,
            skip_keywords=args.skip_keywords,
            adapter_mode=args.adapter,
            skip_pdf=args.skip_pdf,
            years=args.years,
        )
        results.sort(key=lambda r: (r.get("state", ""), r.get("council", "")))

        if not finished:
            # Written while the redirect is still in place: an abandoned
            # thread that print()s from here on lands in the buffer, not in
            # the middle of the JSON.
            timed_out = [
                r["council"]
                for r in results
                if not r["ok"] and r["error"]["type"] == "Timeout"
            ]
            logging.error(
                f"Adapter budget of {budget_s:.0f}s reached; reporting "
                f"{', '.join(timed_out)} as Timeout and exiting without "
                f"waiting for them"
            )
            if args.format == "json":
                _write_json(real_stdout, args, results)
            # os._exit skips Selenium's cleanup, so an abandoned scraper's
            # Chrome would outlive the process. Kill it first—but nothing
            # here may stop _hard_exit from running, or the process hangs.
            for scraper in selected:
                if scraper.council_name in timed_out:
                    try:
                        scraper.fetcher.abandon()
                    except Exception as e:
                        scraper.logger.warning(f"Could not kill its browser: {e}")
            _hard_exit()

    # JSON output mode: stdout should contain JSON ONLY
    if args.format == "json":
        _write_json(sys.stdout, args, results)
        return

    logging.info(f"YIMBY SCRAPER Finished in {time.time() - start_time:.2f}s")


def run_scraper(
    scraper: BaseScraper,
    skip_keywords: bool = False,
    adapter_mode: bool = False,
    skip_pdf: bool = False,
    years: list[int] = None,
):
    # Reported per council so a slow scraper can be named from the adapter's
    # output alone; nothing else times scrapers in production. council-alerts'
    # zod schema strips keys it does not declare, so ingest ignores the field
    # until it chooses to read it. `egress` rides along the same way: it says
    # which councils depended on the home proxy, so a night when only those
    # failed can be read off the output (packages/scraper-adapter/src/schema.ts,
    # checked 19 Oct 2026: plain z.object, unknown keys stripped).
    started = time.monotonic()
    try:
        scraper.logger.info("Scraper started")

        # Pass year filter to scraper so it can optimise (e.g. skip pagination)
        if years:
            scraper.years_filter = years

        results = get_agenda_info(scraper, adapter_mode=adapter_mode)

        # Filter by years if specified
        if years:
            results = [
                r for r in results if r.cleaned_date and r.cleaned_date.year in years
            ]
            scraper.logger.info(f"Filtered to {len(results)} meetings in years {years}")

        # In adapter mode, return all meetings in JSON format
        if adapter_mode:
            meetings = []
            for result in results:
                date_value = (
                    result.cleaned_date.isoformat() if result.cleaned_date else None
                )
                time_value = (
                    result.cleaned_time.isoformat() if result.cleaned_time else None
                )

                meetings.append(
                    {
                        "name": result.name,
                        "date": date_value,
                        "time": time_value,
                        "webpage_url": result.webpage_url,
                        "agenda_url": result.agenda_url,
                        "minutes_url": result.minutes_url,
                        "agenda_html_url": result.agenda_html_url,
                        "minutes_html_url": result.minutes_html_url,
                        "download_url": result.download_url,
                        "location": getattr(result, "location", None)
                        or getattr(result, "cleaned_location", None),
                    }
                )

            scraper.logger.info(
                f"Scraper finished successfully with {len(meetings)} meetings"
            )
            return {
                "ok": True,
                "council": scraper.council_name,
                "state": scraper.state.upper(),
                "meetings": meetings,  # Changed from "meeting" to "meetings" (array)
                "elapsed_s": round(time.monotonic() - started, 1),
                "egress": scraper.egress,
            }

        # Legacy mode: process only the first meeting (backward compatibility)
        if not results:
            scraper.logger.info("No meetings found")
            return None

        result = results[0]  # Take first meeting for legacy mode

        # Skip if already scraped (legacy mode only)
        # Only skip if BOTH agenda and minutes URLs match a previous scrape
        # This allows re-scraping when minutes are added later
        if not adapter_mode:
            # Determine the agenda URL to check
            agenda_url = result.agenda_url or result.download_url
            minutes_url = result.minutes_url

            if db.check_meeting_fully_scraped(agenda_url, minutes_url):
                scraper.logger.info(
                    "Skipping scraper, meeting already fully scraped "
                    f"(agenda: {bool(agenda_url)}, minutes: {bool(minutes_url)})"
                )
                return None
            else:
                scraper.logger.info(
                    f"Processing meeting (agenda: {bool(agenda_url)}, minutes: {bool(minutes_url)})"
                )

        agenda_keywords = {}
        minutes_keywords = {}
        agenda_wordcount = None
        minutes_wordcount = None
        if (not skip_keywords) and (not skip_pdf) and (not adapter_mode):
            agenda_keywords, minutes_keywords, agenda_wordcount, minutes_wordcount = (
                process_pdfs(scraper, result)
            )

        # Combine keywords from both documents
        extracted_keywords = combine_keywords(agenda_keywords, minutes_keywords)

        if not adapter_mode:
            db.insert_result(
                council_name=scraper.council_name,
                state=scraper.state,
                scraper_result=result,
                keywords=extracted_keywords,
                agenda_wordcount=agenda_wordcount,
                minutes_wordcount=minutes_wordcount,
            )
            scraper.logger.info("Saved meeting details to db")

        if not adapter_mode:
            if not result.is_date_in_past(scraper.state):
                notify_email(scraper, result, extracted_keywords)
                notify_discord(scraper, result)
            else:
                scraper.logger.warning(
                    "Skipping notification because date is in the past"
                )

        scraper.logger.info("Scraper finished successfully")

        # Adapter output: JSON-safe primitives only (force strings for date/time)
        date_value = result.cleaned_date.isoformat() if result.cleaned_date else None
        time_value = result.cleaned_time.isoformat() if result.cleaned_time else None

        return {
            "ok": True,
            "council": scraper.council_name,
            "state": scraper.state.upper(),
            "meeting": {
                "name": result.name,
                "date": date_value,
                "time": time_value,
                "webpage_url": result.webpage_url,
                "agenda_url": result.agenda_url,
                "minutes_url": result.minutes_url,
                "download_url": result.download_url,  # Kept for backward compatibility
            },
            "location": getattr(result, "location", None)
            or getattr(result, "cleaned_location", None),
            "elapsed_s": round(time.monotonic() - started, 1),
            "egress": scraper.egress,
        }

    except Exception as e:
        scraper.logger.exception(f"Scraper failed: {e}")

        if not adapter_mode:
            try:
                db.insert_error(
                    council_name=scraper.council_name,
                    state=scraper.state,
                    exception=e,
                )
            except Exception as e2:
                logging.exception(f"YIMBY SCRAPER Fatal Error {e2}")
                os._exit(1)

        # Adapter mode: structured, machine-friendly error
        return {
            "ok": False,
            "council": scraper.council_name,
            "state": scraper.state.upper(),
            "error": {
                "type": type(e).__name__,
                "message": str(e),
            },
            "elapsed_s": round(time.monotonic() - started, 1),
            "egress": scraper.egress,
        }
    finally:
        # Each scraper's Chrome otherwise lives until the process exits, so a
        # run with 10 workers piles up every browser any council opened. A
        # failure to close is logged, never raised: it must not turn a
        # finished council into a failed one.
        try:
            scraper.fetcher.close()
        except Exception as e:
            scraper.logger.warning(f"Could not close its browser: {e}")


def get_agenda_info(scraper: BaseScraper, adapter_mode: bool = False) -> list[ScraperReturn]:
    scraper.logger.info("Finding agenda...")
    results = scraper.scraper()
    scraper.logger.debug(f"Found {len(results)} meetings")

    processed_results = []
    for result in results:
        result.add_default_values(
            default_name=scraper.default_name,
            default_time=scraper.default_time,
            default_location=scraper.default_location,
        )

        result.check_required_properties(scraper.state)

        if not result.cleaned_time and result.time:
            scraper.logger.warning(f"Time found but could not be parsed: {result.time}")

        if result.is_date_in_past(scraper.state):
            if adapter_mode:
                scraper.logger.debug(f"Date is in the past: {result.cleaned_date}")
            else:
                scraper.logger.warning(f"Date is in the past: {result.cleaned_date}")

        processed_results.append(result)

    return processed_results


def process_pdf(
    scraper: BaseScraper, result: ScraperReturn
) -> tuple[KeywordCounts, int]:
    scraper.logger.info("Downloading PDF...")
    download_pdf(result.download_url, scraper.council_name)

    scraper.logger.info("Reading PDF...")
    council_name = scraper.council_name
    text = read_pdf(council_name)
    with open(f"files/{council_name}_latest.txt", "w", encoding="utf-8") as f:
        f.write(text)

    keywords, wordcount = extract_keywords(scraper.keyword_regexes, text)
    scraper.logger.debug(f"Extracted PDF keywords: {json.dumps(keywords, indent=2)}")

    if not config.get("SAVE_FILES", "0") == "1":
        if os.path.exists(f"files/{scraper.council_name}_latest.pdf"):
            os.remove(f"files/{scraper.council_name}_latest.pdf")
        if os.path.exists(f"files/{scraper.council_name}_latest.txt"):
            os.remove(f"files/{scraper.council_name}_latest.txt")

    return keywords, wordcount


def process_pdfs(
    scraper: BaseScraper, result: ScraperReturn
) -> tuple[KeywordCounts, KeywordCounts, int, int]:
    """Process both agenda and minutes PDFs if available.

    Returns:
        tuple: (agenda_keywords, minutes_keywords, agenda_wordcount, minutes_wordcount)
    """
    agenda_keywords = {}
    minutes_keywords = {}
    agenda_wordcount = None
    minutes_wordcount = None

    # For backward compatibility, check download_url first
    if result.download_url:
        scraper.logger.info("Processing legacy download_url as agenda...")
        agenda_keywords, agenda_wordcount = process_single_pdf(
            scraper, result.download_url, "agenda"
        )

    # Process agenda_url if specified
    if result.agenda_url and result.agenda_url != result.download_url:
        scraper.logger.info("Processing agenda PDF...")
        agenda_keywords, agenda_wordcount = process_single_pdf(
            scraper, result.agenda_url, "agenda"
        )

    # Process minutes_url if specified
    if result.minutes_url:
        scraper.logger.info("Processing minutes PDF...")
        minutes_keywords, minutes_wordcount = process_single_pdf(
            scraper, result.minutes_url, "minutes"
        )

    return agenda_keywords, minutes_keywords, agenda_wordcount, minutes_wordcount


def process_single_pdf(
    scraper: BaseScraper, pdf_url: str, doc_type: str
) -> tuple[KeywordCounts, int]:
    """Process a single PDF (agenda or minutes).

    Args:
        scraper: The scraper instance
        pdf_url: URL of the PDF to download
        doc_type: Type of document ('agenda' or 'minutes')

    Returns:
        tuple: (keywords, wordcount)
    """
    council_name = scraper.council_name
    filename = f"{council_name}_{doc_type}"

    scraper.logger.info(f"Downloading {doc_type} PDF...")
    download_pdf(pdf_url, filename)

    scraper.logger.info(f"Reading {doc_type} PDF...")
    text = read_pdf(filename)

    with open(f"files/{filename}.txt", "w", encoding="utf-8") as f:
        f.write(text)

    keywords, wordcount = extract_keywords(scraper.keyword_regexes, text)
    scraper.logger.debug(
        f"Extracted {doc_type} keywords: {json.dumps(keywords, indent=2)}"
    )

    if not config.get("SAVE_FILES", "0") == "1":
        if os.path.exists(f"files/{filename}.pdf"):
            os.remove(f"files/{filename}.pdf")
        if os.path.exists(f"files/{filename}.txt"):
            os.remove(f"files/{filename}.txt")

    return keywords, wordcount


def combine_keywords(
    agenda_keywords: KeywordCounts, minutes_keywords: KeywordCounts
) -> KeywordCounts:
    """Combine keyword counts from agenda and minutes.

    Args:
        agenda_keywords: Keywords extracted from agenda
        minutes_keywords: Keywords extracted from minutes

    Returns:
        Combined keyword counts
    """
    combined = {}

    # Add all agenda keywords
    for key, value in agenda_keywords.items():
        combined[key] = value

    # Add minutes keywords, summing counts if key exists
    for key, value in minutes_keywords.items():
        if key in combined:
            combined[key] += value
        else:
            combined[key] = value

    return combined


def notify_email(
    scraper: BaseScraper, result: ScraperReturn, extracted_data: KeywordCounts
):
    email_to = config.get("GMAIL_ACCOUNT_RECEIVE", None)
    email_enabled = config.get("GMAIL_FUNCTIONALITY", "0") == "1"

    if email_to and email_enabled:
        scraper.logger.info("Sending email...")

        formatted_date = format_date_for_message(result.cleaned_date)
        subject = f"New agenda: {scraper.council_name} {formatted_date} meeting"
        body = write_email(scraper.council_name, result, extracted_data)
        send_email(email_to, subject, body)

        scraper.logger.info("Sent email")


def notify_discord(scraper: BaseScraper, result: ScraperReturn):
    discord_token = config.get("DISCORD_TOKEN", None)
    channel_id = config.get("DISCORD_CHANNEL_ID", None)
    discord_group_tag = config.get("DISCORD_GROUP_TAG", "<@&1111808815097196585>")

    if discord_token and channel_id:
        scraper.logger.info("Sending discord message...")

        discord = DiscordNotifier(discord_token)
        formatted_date = format_date_for_message(result.cleaned_date)

        # Build message with available documents
        message = f"{discord_group_tag}: New documents for {scraper.council_name} {formatted_date}"

        if result.agenda_url:
            message += f"\nAgenda: {result.agenda_url}"

        if result.minutes_url:
            message += f"\nMinutes: {result.minutes_url}"

        # Fallback to download_url for backward compatibility
        if not result.agenda_url and not result.minutes_url and result.download_url:
            message += f"\n{result.download_url}"

        discord.send_message(channel_id, message)
        discord.flush()

        scraper.logger.info("Discord message sent")


if __name__ == "__main__":
    main()
