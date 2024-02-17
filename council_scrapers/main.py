import argparse
import os.path
import importlib
from pathlib import Path
import logging
from council_scrapers.utils import (
    download_pdf,
    read_pdf,
    parse_pdf,
    write_email,
    send_email,
)
import council_scrapers.database as db
from council_scrapers.base import SCRAPER_REGISTRY, BaseScraper, ScraperReturn
from council_scrapers.logging_config import setup_logging
import logging

from council_scrapers.discord_bot import DiscordNotifier

from dotenv import dotenv_values


config = dotenv_values(".env")


def processor(scraper_results: ScraperReturn, scraper: BaseScraper):
    # Assuming council_name matches with your council names, adjust as necessary
    council_name = scraper.council_name
    if not scraper_results.download_url:
        logging.error(f"No link found for {council_name}.")
        return
    if db.check_url(scraper_results.download_url):
        logging.warning(f"Link already scraped for {council_name}.")
        return
    logging.info("Link scraped! Downloading PDF...")
    download_pdf(scraper_results.download_url, council_name)

    logging.info("PDF downloaded!")
    logging.info("Reading PDF into memory...")
    text = read_pdf(council_name)
    with open(f"files/{council_name}_latest.txt", "w", encoding="utf-8") as f:
        f.write(text)

    logging.info("PDF read! Parsing PDF...")
    parser_results = parse_pdf(scraper.keyword_regexes, text)

    email_to = config.get("GMAIL_ACCOUNT_RECEIVE", None)

    if email_to:
        logging.info("Sending email...")
        email_body = write_email(council_name, scraper_results, parser_results)

        send_email(
            email_to,
            f"New agenda: {council_name} {scraper_results.date} meeting",
            email_body,
        )

    discord_token = config.get("DISCORD_TOKEN", None)
    channel_id = config.get("DISCORD_CHANNEL_ID", None)
    if discord_token and channel_id:

        print("Discord notifier initialising...")
        discord = DiscordNotifier(discord_token)

        group_tag = "<@&1111808815097196585>"
        message = f"{group_tag}: New agenda for {council_name} {scraper_results.date} {scraper_results.download_url}"

        discord.send_message(
            channel_id,
            message,
        )
        discord.flush()

    logging.info("PDF parsed! Inserting into database...")
    db.insert(council_name, scraper_results, parser_results)
    print("Database updated!")

    if not config.get("SAVE_FILES", "0") == "1":
        (
            os.remove(f"files/{council_name}_latest.pdf")
            if os.path.exists(f"files/{council_name}_latest.pdf")
            else None
        )
        (
            os.remove(f"files/{council_name}_latest.txt")
            if os.path.exists(f"files/{council_name}_latest.txt")
            else None
        )

    logging.info(f"Finished with {council_name}.")


def run_scrapers(args):
    for scraper_name, scraper_instance in SCRAPER_REGISTRY.items():
        if args.council is None or scraper_instance.council_name == args.council:
            logging.error(f"Running {scraper_instance.council_name} scraper")
            scraper_results = scraper_instance.scraper()
            state = scraper_instance.state
            if scraper_results:
                # Process the result
                processor(scraper_results, scraper_instance)
            else:
                logging.error(
                    f"Something broke, {scraper_instance.council_name} scraper returned 'None'"
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--council", help="Scan only this council")
    args = parser.parse_args()

    if not os.path.exists("./agendas.db"):
        db.init()

    run_scrapers(args)


if __name__ == "__main__":
    setup_logging(level="INFO")
    logging.getLogger().name = "YIMBY-Scraper"
    logging.info("YIMBY SCRAPER Start")
    main()
