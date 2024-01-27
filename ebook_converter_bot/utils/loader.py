"""Bot modules dynamic loader."""

import logging

# This code is adapted from
# https://github.com/PaulSonOfLars/tgbot/blob/master/tg_bot/modules/__init__.py
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)


def get_modules(modules_path: Path) -> list[Path]:
    """Return all modules available in modules directory"""
    return list(
        filter(
            lambda x: x.name != "__init__.py" and x.suffix == ".py" and x.is_file(),
            modules_path.glob("*.py"),
        )
    )


def load_modules(modules: list[Path], directory: str) -> None:
    """Load all modules in modules list"""
    for module in modules:
        import_module(f"{directory}.modules.{module.stem}")
