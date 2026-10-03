"""Process-wide logging for ``copytrade run``: a console handler and a rotating file under ``<data root>/logs``."""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

LOG_FILE_NAME = "copytrade.log"
_LOGGER_NAME = "copytrade"
_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_OURS = "_copytrade_run_handler"
_VALUE_CAP = 200
_LINE_BREAKS = re.compile(r"\r\n|\r|\n")
_STANDARD_ATTRIBUTES = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


def _render(value: object) -> str:
    """One-line, capped text of an extra value; never raises."""
    try:
        text = str(value)
    except Exception:
        text = "<unprintable>"
    return _LINE_BREAKS.sub(" ", text)[:_VALUE_CAP]


class _ExtrasFormatter(logging.Formatter):
    """The standard line plus the record's ``extra`` fields as `` key=value`` (sorted by key). A pair already
    present in the message text is not repeated. ``SecretValue`` renders as ``<redacted>`` through its ``str``."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        message = record.getMessage()
        pairs = []
        for key in sorted(set(vars(record)) - _STANDARD_ATTRIBUTES):
            pair = f"{key}={_render(vars(record)[key])}"
            if not re.search(rf"(?<!\w){re.escape(pair)}(?!\w)", message):
                pairs.append(pair)
        if not pairs:
            return line
        head, sep, tail = line.partition("\n")
        return f"{head} {' '.join(pairs)}{sep}{tail}"


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
    formatter = _ExtrasFormatter(_FORMAT)
    console = logging.StreamHandler(sys.stderr)
    file = logging.handlers.RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    for handler in (console, file):
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        setattr(handler, _OURS, True)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path
