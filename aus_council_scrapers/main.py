import argparse
import json
import logging
import os.path
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


def main():

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", help="Force re-scrape", action="store_true")
    parser.add_argument("--council", help="Scan only this council")
    parser.add_argument("--log-level", help="Set the log level", default="INFO")
    args = parser.parse_args()

    # Setup logging
    if args.log_level:
        setup_logging(level=args.log_level)
        logging.getLogger().name = "YIMBY-Scraper"
        logging.getLogger().setLevel(logging.INFO)
    logging.info("YIMBY SCRAPER Started")

    # Delete db if fresh
    if args.fresh:
        os.remove("./agendas.db")

    # Create db if not exists
    if not os.path.exists("./agendas.db"):
        db.init()

    # Run scrapers
    for scraper in SCRAPER_REGISTRY.values():
        if args.council is None or scraper.council_name == args.council:
            run_scraper(scraper)

    logging.info("YIMBY SCRAPER Finished")


def run_scraper(scraper: BaseScraper):
    try:
        scraper.logger.info(f"Scraper started")

        # Get agenda info
        result = get_agenda_info(scraper)

        # Skip if already scraped
        if db.check_url(result.download_url):
            scraper.logger.info(f"Skipping scraper, URL already scraped.")
            return

        # Extract data from PDF
        extracted_data = process_pdf(scraper, result)

        # Insert into database
        db.insert(scraper.council_name, result, extracted_data)
        scraper.logger.info(f"Saved meeting details to db")

        # Send to email and/or discord
        notify_email(scraper, result, extracted_data)
        notify_discord(scraper, result)

        scraper.logger.info(f"Scraper finished successfully")
    except Exception as e:
        # Save error to log
        scraper.logger.error(f"Scraper failed: {e}")


def get_agenda_info(scraper: BaseScraper) -> Optional[ScraperReturn]:
    # Run the scraper
    scraper.logger.info(f"Finding agenda...")
    result = scraper.scraper()
    scraper.logger.debug(f"Found agenda: {result}")

    # Get result values with defaults
    result.add_default_values(
        default_name=scraper.default_name,
        default_time=scraper.default_time,
        default_location=scraper.default_location,
    )

    # Check result properties
    result.check_required_properties()

    # Log warning if time found but not parsed
    if not result.cleaned_time and result.time:
        scraper.logger.warning(f"Time found but could not be parsed: {result.time}")

    return result


def process_pdf(scraper: BaseScraper, result: ScraperReturn) -> KeywordCounts:
    # Download PDF
    scraper.logger.info(f"Downloading PDF...")
    download_pdf(result.download_url, scraper.council_name)

    # Read pdf into text file
    scraper.logger.info(f"Reading PDF...")
    council_name = scraper.council_name
    text = read_pdf(council_name)
    with open(f"files/{council_name}_latest.txt", "w", encoding="utf-8") as f:
        f.write(text)

    # Extract info from text
    extracted_data = extract_keywords(scraper.keyword_regexes, text)
    scraper.logger.debug(
        f"Extracted PDF keywords: {json.dumps(extracted_data, indent=2)}"
    )

    # Cleanup files if not saving
    if not config.get("SAVE_FILES", "0") == "1":
        (
            os.remove(f"files/{scraper.council_name}_latest.pdf")
            if os.path.exists(f"files/{scraper.council_name}_latest.pdf")
            else None
        )
        (
            os.remove(f"files/{scraper.council_name}_latest.txt")
            if os.path.exists(f"files/{scraper.council_name}_latest.txt")
            else None
        )

    return extracted_data


def notify_email(
    scraper: BaseScraper,
    result: ScraperReturn,
    extracted_data: KeywordCounts,
):
    email_to = config.get("GMAIL_ACCOUNT_RECEIVE", None)

    if email_to:
        scraper.logger.info(f"Sending email...")

        formatted_date = format_date_for_message(result.cleaned_date)
        subject = f"New agenda: {scraper.council_name} {formatted_date} meeting"
        body = write_email(scraper.council_name, result, extracted_data)
        send_email(email_to, subject, body)

        scraper.logger.info(f"Sent email")


def notify_discord(scraper: BaseScraper, result: ScraperReturn):

    # Get env vars
    discord_token = config.get("DISCORD_TOKEN", None)
    channel_id = config.get("DISCORD_CHANNEL_ID", None)
    discord_group_tag = config.get("DISCORD_GROUP_TAG", "<@&1111808815097196585>")

    # Send message if token and channel id
    if discord_token and channel_id:
        scraper.logger.info(f"Sending discord message...")

        discord = DiscordNotifier(discord_token)

        formatted_date = format_date_for_message(result.cleaned_date)
        message = f"{discord_group_tag}: New agenda for {scraper.council_name} {formatted_date} {result.download_url}"
        discord.send_message(channel_id, message)
        discord.flush()

        scraper.logger.info(f"Discord message sent")


if __name__ == "__main__":
    main()
