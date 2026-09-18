"""Single logging initialization path for the application."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from sikumon.config.constants import APP_NAME, APP_VERSION, LOG_FILENAME
from sikumon.storage.paths import ApplicationPaths


def configure_logging(paths: ApplicationPaths, level: int = logging.INFO) -> logging.Logger:
    paths.logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sikumon")
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    handler = RotatingFileHandler(
        paths.logs / LOG_FILENAME,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.info("Starting %s version %s", APP_NAME, APP_VERSION)
    return logger

