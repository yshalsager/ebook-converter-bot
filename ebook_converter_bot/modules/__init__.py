""" Bot modules loader"""
from pathlib import Path

from ebook_converter_bot import LOGGER
from ebook_converter_bot.utils.loader import get_modules

ALL_MODULES = get_modules(Path(__file__).parent)
LOGGER.info("Modules to load: %s", str(ALL_MODULES))
# __all__ = ALL_MODULES + ["ALL_MODULES"]
