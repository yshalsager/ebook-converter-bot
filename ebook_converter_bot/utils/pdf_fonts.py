import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

PDF_FONTS_DIR = Path(__file__).resolve().parents[1] / "data" / "fonts" / "pdf"
PDF_EXTRA_FONTS_DIR_ENV = "PDF_EXTRA_FONTS_DIR"
PDF_FONT_CSS_CACHE_DIR = Path("/tmp/ebook_converter_bot/pdf-font-css")  # noqa: S108
PDF_FONT_ID_RE = re.compile(r"^[a-z0-9_]+$")
FONT_EXTENSIONS = {".otf", ".ttf"}
BUILTIN_FONT_ORDER = (
    "noto_naskh_arabic",
    "amiri",
    "scheherazade_new",
    "kfgqpc_uthman_taha",
    "adwaa_lotfi",
    "ibm_plex_sans_arabic",
    "vazirmatn",
)


@dataclass(frozen=True)
class PdfFontProfile:
    id: str
    label: str
    family: str
    regular_path: Path
    bold_path: Path | None = None
    bold_family: str | None = None
    fallback: str = "serif"

    @property
    def required_files(self) -> tuple[Path, ...]:
        return (self.regular_path, *((self.bold_path,) if self.bold_path else ()))

    def ensure_css(self) -> Path:
        PDF_FONT_CSS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        css_path = PDF_FONT_CSS_CACHE_DIR / f"{self.id}.css"
        css_content = _css_for_profile(self)
        if not css_path.exists() or css_path.read_text() != css_content:
            css_path.write_text(css_content)
        return css_path


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _css_for_profile(profile: PdfFontProfile) -> str:
    family = _css_string(profile.family)
    fallback = profile.fallback
    css = f'body, p, div, li, td, th, blockquote, span {{\n  font-family: "{family}", {fallback} !important;\n}}\n'
    if not (profile.bold_path and profile.bold_family and profile.bold_family != profile.family):
        return css
    bold_family = _css_string(profile.bold_family)
    return (
        css
        + f'\nb, strong, h1, h2, h3, h4, h5, h6 {{\n  font-family: "{bold_family}", "{family}", {fallback} !important;\n}}\n'
    )


def _font_family(path: Path) -> str | None:
    try:
        font = TTFont(path, lazy=True)
    except Exception as error:  # noqa: BLE001
        logger.warning("Failed to read font metadata from %s: %s", path, error)
        return None
    try:
        for name_id in (1, 16):
            names = sorted(
                {
                    value
                    for name in font["name"].names
                    if name.nameID == name_id and (value := name.toUnicode().strip())
                }
            )
            if names:
                return names[0]
    finally:
        font.close()
    return None


def _load_manifest(profile_dir: Path) -> dict[str, str]:
    manifest_path = profile_dir / "profile.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Ignoring invalid PDF font profile %s: %s", manifest_path, error)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring PDF font profile %s because it is not an object", manifest_path)
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _font_files(profile_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in profile_dir.iterdir()
        if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS
    )


def _find_font_file(profile_dir: Path, manifest: dict[str, str], key: str) -> Path | None:
    if value := manifest.get(key):
        root = profile_dir.resolve()
        path = (profile_dir / value).resolve()
        if root not in path.parents or path.suffix.lower() not in FONT_EXTENSIONS:
            logger.warning("Ignoring unsafe PDF font path for %s in %s", key, profile_dir)
        elif path.exists():
            return path
    for name in (f"{key}.ttf", f"{key}.otf"):
        path = profile_dir / name
        if path.exists():
            return path
    font_files = _font_files(profile_dir)
    matching = [path for path in font_files if key in path.stem.lower()]
    if matching:
        return matching[0]
    if key == "regular":
        non_bold = [path for path in font_files if "bold" not in path.stem.lower()]
        return (non_bold or font_files or [None])[0]
    return None


def _load_profile(profile_dir: Path) -> PdfFontProfile | None:
    profile_id = profile_dir.name
    if not PDF_FONT_ID_RE.fullmatch(profile_id):
        logger.warning("Ignoring PDF font profile with unsafe id: %s", profile_id)
        return None
    manifest = _load_manifest(profile_dir)
    regular_path = _find_font_file(profile_dir, manifest, "regular")
    if not regular_path:
        logger.warning("Ignoring PDF font profile %s because regular font is missing", profile_id)
        return None
    family = manifest.get("family") or _font_family(regular_path)
    if not family:
        logger.warning("Ignoring PDF font profile %s because font family is unknown", profile_id)
        return None
    bold_path = _find_font_file(profile_dir, manifest, "bold")
    return PdfFontProfile(
        id=profile_id,
        label=manifest.get("label", " ".join(part.capitalize() for part in profile_id.split("_"))),
        family=family,
        regular_path=regular_path,
        bold_path=bold_path,
        bold_family=manifest.get("bold_family") or (_font_family(bold_path) if bold_path else None),
        fallback=manifest.get("fallback", "serif"),
    )


def _profile_dirs(root: Path) -> list[Path]:
    return (
        sorted(path for path in root.iterdir() if path.is_dir() and path.name != "licenses")
        if root.exists()
        else []
    )


def _font_roots() -> list[Path]:
    return [
        PDF_FONTS_DIR,
        *([Path(extra_root)] if (extra_root := os.getenv(PDF_EXTRA_FONTS_DIR_ENV)) else []),
    ]


@lru_cache(maxsize=1)
def get_pdf_font_profiles() -> dict[str, PdfFontProfile]:
    profiles = {
        profile.id: profile
        for root in _font_roots()
        for profile_dir in _profile_dirs(root)
        if (profile := _load_profile(profile_dir))
    }
    return dict(
        sorted(
            profiles.items(),
            key=lambda item: (
                (0, BUILTIN_FONT_ORDER.index(item[0]), item[1].label.lower())
                if item[0] in BUILTIN_FONT_ORDER
                else (1, len(BUILTIN_FONT_ORDER), item[1].label.lower())
            ),
        )
    )


def get_pdf_font_profile(profile_id: str) -> PdfFontProfile | None:
    return get_pdf_font_profiles().get(profile_id)


def get_pdf_font_option_specs() -> tuple[tuple[str, str], ...]:
    return (
        ("default", "default_label"),
        *(
            (
                profile.id,
                f"{profile.id}_label" if profile.id in BUILTIN_FONT_ORDER else profile.label,
            )
            for profile in get_pdf_font_profiles().values()
        ),
    )


def get_pdf_font_value_map() -> dict[str, str | int | None]:
    return {"default": "default"} | {
        profile_id: profile_id for profile_id in get_pdf_font_profiles()
    }


def get_pdf_font_label(profile_id: str, labels: dict[str, str]) -> str:
    profile = get_pdf_font_profile(profile_id)
    if not profile:
        return profile_id.replace("_", " ")
    return labels.get(
        f"{profile_id}_label" if profile_id in BUILTIN_FONT_ORDER else "", profile.label
    )


def log_pdf_font_profiles() -> None:
    profiles = get_pdf_font_profiles()
    logger.info("Discovered %d PDF font profiles", len(profiles))
    for profile in profiles.values():
        logger.info(
            "PDF font profile: id=%s label=%s family=%s path=%s",
            profile.id,
            profile.label,
            profile.family,
            profile.regular_path.parent,
        )


def refresh_pdf_font_cache() -> None:
    fc_cache = shutil.which("fc-cache")
    if not fc_cache:
        return
    for font_dir in _font_roots():
        if font_dir.exists():
            subprocess.run([fc_cache, "-f", str(font_dir)], check=False)  # noqa: S603
    for cache_file in (Path.home() / ".cache" / "calibre").glob("*font*"):
        if cache_file.is_file():
            cache_file.unlink(missing_ok=True)
