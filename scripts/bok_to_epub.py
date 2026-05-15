# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "access-parser==0.0.6",
# ]
# ///

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_bok_to_epub():
    mod_path = (
        Path(__file__).resolve().parents[1] / "ebook_converter_bot" / "utils" / "bok_to_epub.py"
    )
    spec = importlib.util.spec_from_file_location("bok_to_epub", mod_path)
    if not spec or not spec.loader:
        raise RuntimeError("failed to load bok_to_epub module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.bok_to_epub


def main() -> None:
    p = argparse.ArgumentParser(description="Convert Shamela old .bok (MDB) to EPUB")
    p.add_argument("inputs", nargs="*", help="Input .bok files (default: *.bok in cwd)")
    p.add_argument(
        "--out-dir", default="bok_epub_out", help="Output directory (default: bok_epub_out)"
    )
    p.add_argument(
        "--include-toc-page", action="store_true", help="Include nav.xhtml in spine (reading order)"
    )
    p.add_argument(
        "--split-numbered", action="store_true", help="Split plain text on numbered/heading lines"
    )
    args = p.parse_args()

    inputs = [Path(x) for x in args.inputs] if args.inputs else sorted(Path().glob("*.bok"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bok_to_epub = load_bok_to_epub()

    for bok in inputs:
        out = out_dir / bok.with_suffix(".epub").name
        bok_to_epub(
            bok, out, include_toc_page=args.include_toc_page, split_numbered=args.split_numbered
        )
        sys.stdout.write(f"{bok.name} -> {out}\n")


if __name__ == "__main__":
    main()
