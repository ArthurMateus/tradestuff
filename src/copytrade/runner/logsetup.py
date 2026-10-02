"""Process-wide logging for ``copytrade run``: a console handler and a rotating file under ``<data root>/logs``."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_FILE_NAME = "copytrade.log"
_LOGGER_NAME = "copytrade"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_OURS = "_copytrade_run_handler"


def configure_logging(log_dir: Path) -> Path:
    """Install the console (INFO) and rotating file (INFO) handlers on the ``copytrade`` logger and return the file
    path. Idempotent: the handlers of an earlier call are replaced, never added to. Secrets never reach a record:
    they are ``SecretValue`` objects that format as ``<redacted>``, and nothing here reads the environment."""
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, _OURS, False):
            logger.removeHandler(handler)
            handler.close()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE_NAME
    formatter = logging.Formatter(_FORMAT)
    console = logging.StreamHandler(sys.stderr)
    file = logging.handlers.RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    for handler in (console, file):
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        setattr(handler, _OURS, True)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path
