import logging
import sys

from pythonjsonlogger.json import JsonFormatter

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """One JSON line per log record on stdout — the shape a log aggregator
    (CloudWatch, Loki, ELK) expects, instead of uvicorn's default plain text.
    Called once at process startup, before the app starts serving."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(LOG_FORMAT, rename_fields={"asctime": "timestamp", "levelname": "level"}))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers on these loggers by default —
    # replace them so access/error logs are also JSON, not plain text.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
