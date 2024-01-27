"""Bot modules loader."""

import logging
from pathlib import Path

from ebook_converter_bot.utils.loader import get_modules

ALL_MODULES: list[Path] = get_modules(Path(__file__).parent)
logging.info(f"Modules to load: [{', '.join(module.stem for module in ALL_MODULES)}]")
# __all__ = ALL_MODULES + ["ALL_MODULES"]
