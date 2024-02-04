import os.path
import importlib
from pathlib import Path
import logging
from logging.config import dictConfig
from functions import download_pdf, read_pdf, parse_pdf, write_email, send_email
import database as db
from _dataclasses import Council
from base_scraper import scraper_registry


# Web scraping
# from scrapers import councils

from dotenv import dotenv_values


config = dotenv_values(".env")


def setup_logging():
    dictConfig({
        'version': 1,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
                'level': 'DEBUG',
                'stream': 'ext://sys.stdout',
            },
            'file': {
                'class': 'logging.FileHandler',
                'formatter': 'standard',
                'level': 'DEBUG',
                'filename': 'application.log',
                'mode': 'a',
            },
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
        },
    })


def dynamic_import_scrapers():
    # Define the root directory for your scrapers relative to this script
    scrapers_root = Path(__file__).parent / 'scrapers'
    
    # Iterate over all .py files in the scrapers directory and subdirectories
    for path in scrapers_root.rglob('*.py'):
        # Skip __init__.py files
        if path.name == '__init__.py':
            continue
        
        # Convert the file path to a Python module path
        module_path = path.relative_to(Path(__file__).parent).with_suffix('')  # Remove the .py suffix
        module_name = '.'.join(module_path.parts)
        logging.info(f"Loading {module_name}")
        # Import the module
        importlib.import_module(module_name)


def processor(council_name, state, scraper_results, scraper_instance):
    # Assuming council_name matches with your council names, adjust as necessary
    council = Council(name=council_name, scraper=scraper_instance)

    if not scraper_results.download_url:
        logging.error(f"No link found for {council.name}.")
        return
    if db.check_url(scraper_results.download_url):
        logging.warning(f"Link already scraped for {council.name}.")
        return

    logging.info("Link scraped! Downloading PDF...")
    download_pdf(scraper_results.download_url, council.name)

    logging.info("PDF downloaded!")
    logging.info("Reading PDF into memory...")
    text = read_pdf(council.name)
    with open(f"files/{council.name}_latest.txt", "w") as f:
        f.write(text)

    logging.info("PDF read! Parsing PDF...")
    parser_results = parse_pdf(council.regexes, text)

    logging.info("Sending email...")

    email_body = write_email(council, scraper_results, parser_results)

    # send_email(
    #     config["GMAIL_ACCOUNT_RECEIVE"],
    #     f"New agenda: {council.name} {scraper_results.date} meeting",
    #     email_body,
    # )

    logging.info("PDF parsed! Inserting into database...")
    db.insert(council, scraper_results, parser_results)
    logging.info("Database updated!")

    # if not config["SAVE_FILES"] == "1":
    #     os.remove(f"files/{council.name}_latest.pdf") if os.path.exists(
    #         f"files/{council.name}_latest.pdf"
    #     ) else None
    #     os.remove(f"files/{council.name}_latest.txt") if os.path.exists(
    #         f"files/{council.name}_latest.txt"
    #     ) else None

    logging.info(f"Finished with {council.name}.")

def run_scrapers():
    for scraper_name, scraper_instance in scraper_registry.items():
        scraper_results = scraper_instance.scraper()
        council_name = scraper_instance.council_name
        state = scraper_instance.state
        # Process the result    
        processor(council_name, state, scraper_results, scraper_instance)


def main():
    if not os.path.exists("./agendas.db"):
        db.init()

    run_scrapers()


if __name__ == "__main__":
    setup_logging()
    dynamic_import_scrapers()
    logging.info("Application start")
    main()
