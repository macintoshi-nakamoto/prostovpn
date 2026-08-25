import logging
import sys
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("prostovpn")

    if log.handlers:
        return log

    log.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    log.addHandler(console)
    log.addHandler(file_handler)

    return log


logger = setup_logger()
