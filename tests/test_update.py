from pathlib import Path
from zipfile import ZipFile

import pytest
from ebook_converter_bot.utils.update import (
    apply_checkout_files,
    build_github_archive_url,
    extract_update_archive,
    get_checkout_dir_from_archive,
)


def test_build_github_archive_url_normalizes_supported_repo_urls() -> None:
    assert (
        build_github_archive_url("https://github.com/yshalsager/ebook-converter-bot.git", "master")
        == "https://codeload.github.com/yshalsager/ebook-converter-bot/zip/refs/heads/master"
    )
    assert (
        build_github_archive_url("git@github.com:yshalsager/ebook-converter-bot.git", "main")
        == "https://codeload.github.com/yshalsager/ebook-converter-bot/zip/refs/heads/main"
    )


def test_build_github_archive_url_rejects_non_github_urls() -> None:
    with pytest.raises(ValueError, match="Unsupported UPDATE_REPO_URL"):
        build_github_archive_url("https://example.com/yshalsager/ebook-converter-bot.git", "master")


def test_get_checkout_dir_from_archive_requires_package_dir(tmp_path: Path) -> None:
    checkout_dir = tmp_path / "ebook-converter-bot-master"
    checkout_dir.mkdir()

    with pytest.raises(RuntimeError, match="missing ebook_converter_bot"):
        get_checkout_dir_from_archive(tmp_path)

    (checkout_dir / "ebook_converter_bot").mkdir()
    assert get_checkout_dir_from_archive(tmp_path) == checkout_dir


def test_apply_checkout_files_replaces_package_and_copies_root_files(tmp_path: Path) -> None:
    checkout_dir = tmp_path / "checkout"
    package_dir = checkout_dir / "ebook_converter_bot"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("new")
    (checkout_dir / "pyproject.toml").write_text("project")
    (checkout_dir / "uv.lock").write_text("lock")

    root_dir = tmp_path / "app"
    old_package_dir = root_dir / "ebook_converter_bot"
    old_package_dir.mkdir(parents=True)
    (old_package_dir / "old.py").write_text("old")

    failures = apply_checkout_files(
        checkout_dir,
        root_dir=root_dir,
        root_files=("pyproject.toml", "uv.lock"),
        dirs=("ebook_converter_bot",),
    )

    assert failures == []
    assert (old_package_dir / "__init__.py").read_text() == "new"
    assert (old_package_dir / "old.py").exists() is False
    assert (root_dir / "pyproject.toml").read_text() == "project"
    assert (root_dir / "uv.lock").read_text() == "lock"


def test_extract_update_archive_rejects_unsafe_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", "evil")

    with pytest.raises(RuntimeError, match="unsafe path"):
        extract_update_archive(archive_path, tmp_path / "extract")
