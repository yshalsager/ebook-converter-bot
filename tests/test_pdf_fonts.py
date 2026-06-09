import json
from pathlib import Path
from shutil import copy2

from ebook_converter_bot.utils.pdf_fonts import (
    PDF_FONTS_DIR,
    get_pdf_font_option_specs,
    get_pdf_font_profiles,
    get_pdf_font_value_map,
)


def _copy_font(profile_dir: Path, target_name: str = "regular.ttf") -> None:
    profile_dir.mkdir(parents=True)
    copy2(PDF_FONTS_DIR / "amiri" / "Amiri-Regular.ttf", profile_dir / target_name)


def test_extra_font_profile_can_be_discovered_without_manifest(tmp_path: Path, monkeypatch) -> None:
    _copy_font(tmp_path / "my_private_font")
    monkeypatch.setenv("PDF_EXTRA_FONTS_DIR", str(tmp_path))
    get_pdf_font_profiles.cache_clear()

    profiles = get_pdf_font_profiles()
    profile = profiles["my_private_font"]

    assert profile.label == "My Private Font"
    assert profile.family == "Amiri"
    assert profile.regular_path == tmp_path / "my_private_font" / "regular.ttf"
    assert ("my_private_font", "My Private Font") in get_pdf_font_option_specs()
    assert get_pdf_font_value_map()["my_private_font"] == "my_private_font"
    assert 'font-family: "Amiri"' in profile.ensure_css().read_text()

    get_pdf_font_profiles.cache_clear()


def test_extra_font_profile_manifest_can_override_label_and_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    profile_dir = tmp_path / "scholarly_font"
    _copy_font(profile_dir, "custom.ttf")
    (profile_dir / "profile.json").write_text(
        json.dumps({"label": "Dense Scholarly Font", "regular": "custom.ttf", "fallback": "serif"})
    )
    monkeypatch.setenv("PDF_EXTRA_FONTS_DIR", str(tmp_path))
    get_pdf_font_profiles.cache_clear()

    profile = get_pdf_font_profiles()["scholarly_font"]

    assert profile.label == "Dense Scholarly Font"
    assert profile.regular_path == profile_dir / "custom.ttf"
    assert 'font-family: "Amiri", serif !important;' in profile.ensure_css().read_text()

    get_pdf_font_profiles.cache_clear()
