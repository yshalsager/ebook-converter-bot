"""Bot initialization."""

import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from sys import stderr, stdout

WORK_DIR = Path(__package__).absolute()
PARENT_DIR = WORK_DIR.parent

# read bot config
CONFIG = json.loads((PARENT_DIR / "config.json").read_text())
API_KEY = CONFIG["api_key"]
API_HASH = CONFIG["api_hash"]
BOT_TOKEN = CONFIG["tg_bot_token"]
BOT_ID = CONFIG["tg_bot_id"]
TG_BOT_ADMINS = CONFIG["tg_bot_admins"]

# locale
LOCALE_PATH = WORK_DIR / "data/locales"
LANGUAGES = ["ar", "en", "tr"]
_ = json.loads(
    Path(WORK_DIR / "data/locales/locales.json").read_text(encoding="utf-8-sig")
)
LOCALES = [_[i] for i in LANGUAGES]
for code, locale in zip(LANGUAGES, LOCALES, strict=True):
    locale["code"] = code

# Logging
LOG_FILE = PARENT_DIR / "last_run.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(module)s.%(funcName)s:%(lineno)d]: %(message)s"
FORMATTER: logging.Formatter = logging.Formatter(LOG_FORMAT)
handler = TimedRotatingFileHandler(LOG_FILE, when="d", interval=1, backupCount=3)
logging.basicConfig(filename=str(LOG_FILE), filemode="w", format=LOG_FORMAT)
OUT = logging.StreamHandler(stdout)
ERR = logging.StreamHandler(stderr)
OUT.setFormatter(FORMATTER)
ERR.setFormatter(FORMATTER)
OUT.setLevel(logging.INFO)
ERR.setLevel(logging.WARNING)
LOGGER = logging.getLogger()
LOGGER.addHandler(OUT)
LOGGER.addHandler(ERR)
LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
