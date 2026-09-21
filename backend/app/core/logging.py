import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_dir / "microcred.log", maxBytes=5_000_000, backupCount=5
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

