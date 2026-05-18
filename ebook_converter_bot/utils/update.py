"""Self-update helpers."""

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import Iterable
from pathlib import Path
from shutil import copy2, copyfileobj, copytree, rmtree
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from ebook_converter_bot import PARENT_DIR

DEFAULT_UPDATE_REPO_URL = "https://github.com/yshalsager/ebook-converter-bot.git"
DEFAULT_UPDATE_REPO_BRANCH = "master"
UPDATE_ROOT_FILES = ("pyproject.toml", "uv.lock", "Dockerfile", "docker-compose.yml", "mise.toml")
UPDATE_DIRS = ("ebook_converter_bot",)
COMMAND_TIMEOUT_SECONDS = 600


def build_github_archive_url(repo_url: str, branch: str) -> str:
    normalized_repo_url = repo_url.strip()
    if normalized_repo_url.startswith("git@github.com:"):
        normalized_repo_url = f"https://github.com/{normalized_repo_url.split(':', 1)[1]}"
    if normalized_repo_url.endswith(".git"):
        normalized_repo_url = normalized_repo_url[:-4]
    if not normalized_repo_url.startswith("https://github.com/"):
        raise ValueError(f"Unsupported UPDATE_REPO_URL: {repo_url}")

    repo_path = normalized_repo_url.removeprefix("https://github.com/").strip("/")
    if not repo_path:
        raise ValueError(f"Unsupported UPDATE_REPO_URL: {repo_url}")
    return f"https://codeload.github.com/{repo_path}/zip/refs/heads/{branch}"


def _download_file(url: str, output_path: Path) -> None:
    with urlopen(url, timeout=300) as response, output_path.open("wb") as output_file:  # noqa: S310
        output_file.write(response.read())


async def download_update_archive(archive_url: str, archive_path: Path) -> None:
    await asyncio.to_thread(_download_file, archive_url, archive_path)


def get_checkout_dir_from_archive(extract_dir: Path) -> Path:
    extracted_dirs = [path for path in extract_dir.iterdir() if path.is_dir()]
    if not extracted_dirs:
        raise RuntimeError("Archive has no extracted directory")
    checkout_dir = extracted_dirs[0]
    if not (checkout_dir / "ebook_converter_bot").exists():
        raise RuntimeError("Archive missing ebook_converter_bot directory")
    return checkout_dir


def extract_update_archive(archive_path: Path, extract_dir: Path) -> None:
    root = extract_dir.resolve()
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (extract_dir / member.filename).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"Archive contains unsafe path: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                copyfileobj(source, output)


def _replace_dir(source: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}.old")
    rmtree(backup, ignore_errors=True)
    if target.exists():
        target.rename(backup)
    try:
        copytree(source, target)
    except Exception:
        rmtree(target, ignore_errors=True)
        if backup.exists():
            backup.rename(target)
        raise
    rmtree(backup, ignore_errors=True)


def apply_checkout_files(
    checkout_dir: Path,
    *,
    root_dir: Path = PARENT_DIR,
    root_files: Iterable[str] = UPDATE_ROOT_FILES,
    dirs: Iterable[str] = UPDATE_DIRS,
) -> list[str]:
    partial_copy_failures: list[str] = []
    for dir_name in dirs:
        _replace_dir(checkout_dir / dir_name, root_dir / dir_name)

    for file_name in root_files:
        source_file = checkout_dir / file_name
        if not source_file.exists():
            continue
        try:
            copy2(source_file, root_dir / file_name)
        except OSError:
            partial_copy_failures.append(file_name)
    return partial_copy_failures


async def update_from_archive(repo_url: str, branch: str) -> list[str]:
    archive_url = build_github_archive_url(repo_url, branch)
    with TemporaryDirectory() as temp_dir:
        archive_path = Path(temp_dir) / "source.zip"
        extract_dir = Path(temp_dir) / "extract"
        await download_update_archive(archive_url, archive_path)
        extract_update_archive(archive_path, extract_dir)
        checkout_dir = get_checkout_dir_from_archive(extract_dir)
        return apply_checkout_files(checkout_dir)


async def run_command(command: list[str], *, cwd: Path = PARENT_DIR) -> tuple[str, int]:
    process = await asyncio.create_subprocess_exec(*command, stdout=PIPE, stderr=PIPE, cwd=cwd)
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        return "Process timed out", -1
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return output, process.returncode or 0


__all__ = [
    "DEFAULT_UPDATE_REPO_BRANCH",
    "DEFAULT_UPDATE_REPO_URL",
    "BadZipFile",
    "apply_checkout_files",
    "build_github_archive_url",
    "extract_update_archive",
    "get_checkout_dir_from_archive",
    "run_command",
    "update_from_archive",
]
