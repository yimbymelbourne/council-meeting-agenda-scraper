# logging_config.py
import logging
from logging.config import dictConfig
import os


APP_NAME = "YIMBY-Scraper"


def setup_logging(level="INFO"):
    # Ensure the log directory exists
    log_directory = os.path.join("logs", APP_NAME)
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    log_file_path = os.path.join(log_directory, f"{APP_NAME}.log")

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": f"%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": "DEBUG",
                    "stream": "ext://sys.stdout",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "formatter": "standard",
                    "level": "DEBUG",
                    "filename": log_file_path,
                    "mode": "a",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": level,
            },
        }
    )
