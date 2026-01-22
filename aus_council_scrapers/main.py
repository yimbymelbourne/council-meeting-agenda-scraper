import argparse
from concurrent.futures import ThreadPoolExecutor
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


def main():

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", help="Force re-scrape", action="store_true")
    parser.add_argument(
        "--skip-keywords", help="Skip keyword extraction", action="store_true"
    )
    parser.add_argument("--council", help="Scan only this council")
    parser.add_argument("--state", help="Scan only this state")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Filter meetings by year(s). Example: --years 2025 or --years 2024 2025",
    )
    parser.add_argument("--log-level", help="Set the log level", default="INFO")
    parser.add_argument("--workers", help="Number of workers", default=6, type=int)
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

    futures = []
    results: list[dict] = []

    # In JSON mode, suppress any accidental prints from scrapers
    with suppress_stdout(args.format == "json"):
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for scraper in SCRAPER_REGISTRY.values():
                # Filter by council and state
                if args.state and args.state.lower() != scraper.state.lower():
                    continue
                if (
                    args.council
                    and args.council.lower() != scraper.council_name.lower()
                ):
                    continue

                futures.append(
                    executor.submit(
                        run_scraper,
                        scraper,
                        skip_keywords=args.skip_keywords,
                        adapter_mode=args.adapter,
                        skip_pdf=args.skip_pdf,
                        years=args.years,
                    )
                )

            # Gather results safely (one failure shouldn't kill JSON output)
            for fut in futures:
                try:
                    out = fut.result()
                except Exception as e:
                    # This catches unexpected exceptions escaping run_scraper
                    logging.exception(f"Worker future failed unexpectedly: {e}")
                    out = {"ok": False, "error": f"{type(e).__name__}: {e}"}

                if out is not None:
                    results.append(out)

    results.sort(key=lambda r: (r.get("state", ""), r.get("council", "")))

    # JSON output mode: stdout should contain JSON ONLY
    if args.format == "json":
        payload = {
            "format_version": 1,
            "adapter_mode": args.adapter,
            "council_filter": args.council,
            "state_filter": args.state,
            "results": results,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=json_default))
        sys.stdout.write("\n")
        return

    logging.info(f"YIMBY SCRAPER Finished in {time.time() - start_time:.2f}s")


def run_scraper(
    scraper: BaseScraper,
    skip_keywords: bool = False,
    adapter_mode: bool = False,
    skip_pdf: bool = False,
    years: list[int] = None,
):
    try:
        scraper.logger.info("Scraper started")

        results = get_agenda_info(scraper)
        
        # Filter by years if specified
        if years:
            results = [
                r for r in results
                if r.cleaned_date and r.cleaned_date.year in years
            ]
            scraper.logger.info(f"Filtered to {len(results)} meetings in years {years}")
        
        # In adapter mode, return all meetings in JSON format
        if adapter_mode:
            meetings = []
            for result in results:
                date_value = result.cleaned_date.isoformat() if result.cleaned_date else None
                time_value = result.cleaned_time.isoformat() if result.cleaned_time else None
                
                meetings.append({
                    "name": result.name,
                    "date": date_value,
                    "time": time_value,
                    "webpage_url": result.webpage_url,
                    "agenda_url": result.agenda_url,
                    "minutes_url": result.minutes_url,
                    "download_url": result.download_url,
                    "location": getattr(result, "location", None) or getattr(result, "cleaned_location", None),
                })
            
            scraper.logger.info(f"Scraper finished successfully with {len(meetings)} meetings")
            return {
                "ok": True,
                "council": scraper.council_name,
                "state": scraper.state.upper(),
                "meetings": meetings,  # Changed from "meeting" to "meetings" (array)
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
        }


def get_agenda_info(scraper: BaseScraper) -> list[ScraperReturn]:
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
