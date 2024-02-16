import os.path
import logging
from council_scrapers.utils import (
    download_pdf,
    read_pdf,
    parse_pdf,
    write_email,
    send_email,
)
import council_scrapers.database as db
from council_scrapers.base import SCRAPER_REGISTRY, BaseScraper
from council_scrapers.constants import COUNCIL_HOUSING_REGEX
from council_scrapers.logging_config import setup_logging
import logging

from dotenv import dotenv_values


config = dotenv_values(".env")


def process_scraper(scraper: BaseScraper):
    # Assuming council_name matches with your council names, adjust as necessary
    scraper_results = scraper.scraper()
    if not scraper_results:
        logging.error(
            f"Something broke, {scraper.council_name} scraper returned 'None'"
        )
        return
    #    Council(name=council_name, scraper=scraper_instance)
    if not scraper_results.download_url:
        logging.error(f"No link found for {scraper.council_name}.")
        return
    if db.check_url(scraper_results.download_url):
        logging.warning(f"Link already scraped for {scraper.council_name}.")
        return
    logging.info("Link scraped! Downloading PDF...")
    download_pdf(scraper_results.download_url, scraper.council_name)

    logging.info("PDF downloaded!")
    logging.info("Reading PDF into memory...")
    text = read_pdf(scraper.council_name)
    with open(f"files/{scraper.council_name}_latest.txt", "w", encoding="utf-8") as f:
        f.write(text)

    logging.info("PDF read! Parsing PDF...")
    parser_results = parse_pdf(COUNCIL_HOUSING_REGEX, text)

    email_to = config.get("GMAIL_ACCOUNT_RECEIVE", None)

    if email_to:
        logging.info("Sending email...")
        email_body = write_email(scraper.council_name, scraper_results, parser_results)

        send_email(
            email_to,
            f"New agenda: {scraper.council_name} {scraper_results.date} meeting",
            email_body,
        )

    logging.info("PDF parsed! Inserting into database...")
    db.insert(scraper.council_name, scraper_results, parser_results)
    print("Database updated!")

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

    logging.info(f"Finished with {scraper.council_name}.")


def run_scrapers():
    for scraper_name, scraper_instance in SCRAPER_REGISTRY.items():
        logging.error(f"Running {scraper_instance.council_name} scraper")
        process_scraper(scraper_instance)


def main():
    if not os.path.exists("./agendas.db"):
        db.init()
    run_scrapers()


if __name__ == "__main__":
    setup_logging(level="INFO")
    logging.getLogger().name = "YIMBY-Scraper"
    logging.info("YIMBY SCRAPER Start")
    main()
