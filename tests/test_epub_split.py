# ruff: noqa: RUF001

import re
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from ebook_converter_bot.utils import epub_split as split_epub

EXPECTED_SPLIT_FILES = 2


def _read_zip_text(epub_path: Path, name: str) -> str:
    with zipfile.ZipFile(epub_path) as zf:
        return zf.read(name).decode()


def _read_zip_text_bytes(epub_bytes: bytes, name: str) -> str:
    with zipfile.ZipFile(BytesIO(epub_bytes)) as zf:
        return zf.read(name).decode()


def _list_text_pages(epub_path: Path) -> list[str]:
    with zipfile.ZipFile(epub_path) as zf:
        return sorted(
            name
            for name in zf.namelist()
            if name.startswith("OEBPS/text/") and name.endswith(".xhtml")
        )


def _write_multi_volume_source(epub_path: Path) -> None:
    info = {
        "title": "كتاب الاختبار",
        "author": "مؤلف",
        "about": "<p>نبذة</p>",
        "toc": [
            {"page": 1, "text": "مقدمة", "anchor": "toc-1"},
            [
                {"page": 3, "text": "القسم الثاني", "anchor": "toc-2"},
                [{"page": 4, "text": "تفصيل", "anchor": "toc-3"}],
            ],
        ],
        "volumes": {},
        "page_chapters": {1: ["مقدمة"], 3: ["القسم الثاني"], 4: ["تفصيل"]},
    }
    pages = [
        {"page_number": 1, "page": 11, "text_html": "<p>نص ١</p>"},
        {"page_number": 2, "page": 12, "text_html": "<p>نص ٢</p>"},
        {"page_number": 3, "page": 13, "text_html": "<p>نص ٣</p>"},
        {"page_number": 4, "page": 14, "text_html": "<p>نص ٤</p>"},
    ]
    epub_bytes = split_epub._build_epub_bytes(info, pages, include_toc_page=True)
    epub_path.write_bytes(epub_bytes)


def _rewrite_zip_entry(epub_path: Path, target_name: str, updated_text: str) -> None:
    temp_path = epub_path.with_suffix(".tmp.epub")
    was_updated = False
    with zipfile.ZipFile(epub_path) as src, zipfile.ZipFile(temp_path, "w") as dst:
        for item in src.infolist():
            if item.filename == target_name:
                data = updated_text.encode()
                was_updated = True
            else:
                data = src.read(item.filename)
            dst.writestr(item, data)
        if not was_updated:
            dst.writestr(target_name, updated_text.encode())
    temp_path.replace(epub_path)


def _rewrite_zip_entry_bytes(epub_path: Path, target_name: str, updated_bytes: bytes) -> None:
    temp_path = epub_path.with_suffix(".tmp.epub")
    was_updated = False
    with zipfile.ZipFile(epub_path) as src, zipfile.ZipFile(temp_path, "w") as dst:
        for item in src.infolist():
            if item.filename == target_name:
                data = updated_bytes
                was_updated = True
            else:
                data = src.read(item.filename)
            dst.writestr(item, data)
        if not was_updated:
            dst.writestr(target_name, updated_bytes)
    temp_path.replace(epub_path)


def _rename_zip_entries(epub_path: Path, rename_map: dict[str, str]) -> None:
    temp_path = epub_path.with_suffix(".tmp.epub")
    with zipfile.ZipFile(epub_path) as src, zipfile.ZipFile(temp_path, "w") as dst:
        for item in src.infolist():
            dst.writestr(rename_map.get(item.filename, item.filename), src.read(item.filename))
    temp_path.replace(epub_path)


def _remove_zip_entries(epub_path: Path, removed_names: set[str]) -> None:
    temp_path = epub_path.with_suffix(".tmp.epub")
    with zipfile.ZipFile(epub_path) as src, zipfile.ZipFile(temp_path, "w") as dst:
        for item in src.infolist():
            if item.filename in removed_names:
                continue
            dst.writestr(item, src.read(item.filename))
    temp_path.replace(epub_path)


def _rewrite_container_rootfile(epub_path: Path, rootfile_path: str) -> None:
    _rewrite_zip_entry(
        epub_path,
        "META-INF/container.xml",
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        f' <rootfiles><rootfile full-path="{rootfile_path}" media-type="application/oebps-package+xml" />'
        " </rootfiles></container>\n",
    )


@pytest.fixture
def make_multi_volume_epub(tmp_path: Path):
    def _make(name: str = "book.epub") -> Path:
        source_epub = tmp_path / name
        _write_multi_volume_source(source_epub)
        return source_epub

    return _make


@pytest.fixture
def make_epub_from_payload(tmp_path: Path):
    def _make(name: str, info: dict, pages: list[dict]) -> Path:
        source_epub = tmp_path / name
        epub_bytes = split_epub._build_epub_bytes(info, pages, include_toc_page=True)
        source_epub.write_bytes(epub_bytes)
        return source_epub

    return _make


def test_split_epub_by_volumes_splits_and_trims_toc(make_multi_volume_epub, tmp_path: Path) -> None:
    source_epub = make_multi_volume_epub()

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    first = tmp_path / "book - 1.epub"
    second = tmp_path / "book - 2.epub"
    assert first in written_files
    assert second in written_files
    assert first.exists()
    assert second.exists()

    first_opf = _read_zip_text(first, "OEBPS/content.opf")
    assert "<dc:title>كتاب الاختبار - 1</dc:title>" in first_opf
    first_info = _read_zip_text(first, "OEBPS/info.xhtml")
    assert "html:" not in first_info
    assert "الجزء:" not in first_info

    assert _list_text_pages(first) == ["OEBPS/text/page_1_01.xhtml", "OEBPS/text/page_1_02.xhtml"]
    assert _list_text_pages(second) == ["OEBPS/text/page_1_03.xhtml", "OEBPS/text/page_1_04.xhtml"]

    first_nav = _read_zip_text(first, "OEBPS/nav.xhtml")
    second_nav = _read_zip_text(second, "OEBPS/nav.xhtml")
    assert "مقدمة" in first_nav
    assert "القسم الثاني" not in first_nav
    assert "القسم الثاني" in second_nav
    assert "مقدمة" not in second_nav


def test_split_epub_by_volumes_skips_single_volume(tmp_path: Path) -> None:
    source_epub = tmp_path / "single.epub"

    info = {
        "title": "مفرد",
        "author": "مؤلف",
        "about": "<p>نبذة</p>",
        "toc": [{"page": 1, "text": "باب", "anchor": "toc-1"}],
        "volumes": {},
        "page_chapters": {1: ["باب"]},
    }
    pages = [{"page_number": 1, "page": 1, "text_html": "<p>نص</p>"}]
    source_epub.write_bytes(split_epub._build_epub_bytes(info, pages, include_toc_page=True))

    assert split_epub.split_epub_by_volumes(source_epub, tmp_path) == []
    assert list(tmp_path.glob("single - *.epub")) == []


def test_split_epub_by_volumes_resolves_package_paths(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("moved_paths.epub")

    _rename_zip_entries(
        source_epub,
        {
            "OEBPS/content.opf": "OEBPS/Content.OPF",
            "OEBPS/info.xhtml": "OEBPS/InfoCard.xhtml",
            "OEBPS/nav.xhtml": "OEBPS/Navigation.xhtml",
        },
    )
    _rewrite_container_rootfile(source_epub, "OEBPS/Content.OPF")
    moved_opf = _read_zip_text(source_epub, "OEBPS/Content.OPF")
    moved_opf = moved_opf.replace('href="info.xhtml"', 'href="InfoCard.xhtml"')
    moved_opf = moved_opf.replace('href="nav.xhtml"', 'href="Navigation.xhtml"')
    _rewrite_zip_entry(source_epub, "OEBPS/Content.OPF", moved_opf)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "moved_paths - 1.epub").exists()
    assert (tmp_path / "moved_paths - 2.epub").exists()


@pytest.mark.parametrize(
    "case",
    [
        {
            "opf_entry_name": "OEBPS/content.opf",
            "asset_entry_name": "OEBPS/images/cover.svg",
            "page_img_src": "../images/cover.svg",
            "manifest_asset_href": "images/cover.svg",
            "expected_manifest_href": "images/cover.svg",
        },
        {
            "opf_entry_name": "content.opf",
            "asset_entry_name": "images/cover.svg",
            "page_img_src": "../../images/cover.svg",
            "manifest_asset_href": "images/cover.svg",
            "expected_manifest_href": "../images/cover.svg",
        },
        {
            "opf_entry_name": "OEBPS/content.opf",
            "asset_entry_name": "OEBPS/text/cover.svg",
            "page_img_src": "cover.svg",
            "manifest_asset_href": "text/cover.svg",
            "expected_manifest_href": "text/cover.svg",
        },
    ],
    ids=["oebps-opf", "root-opf", "text-asset-path"],
)
def test_split_epub_by_volumes_copies_assets_and_manifest_hrefs(
    make_multi_volume_epub,
    tmp_path: Path,
    case: dict[str, str],
) -> None:
    opf_entry_name = case["opf_entry_name"]
    asset_entry_name = case["asset_entry_name"]
    page_img_src = case["page_img_src"]
    manifest_asset_href = case["manifest_asset_href"]
    expected_manifest_href = case["expected_manifest_href"]

    source_epub = make_multi_volume_epub("assets.epub")
    if opf_entry_name == "content.opf":
        _rename_zip_entries(
            source_epub,
            {
                "OEBPS/content.opf": "content.opf",
                "OEBPS/info.xhtml": "info.xhtml",
                "OEBPS/nav.xhtml": "nav.xhtml",
            },
        )
        _rewrite_container_rootfile(source_epub, "content.opf")

    first_page = _read_zip_text(source_epub, "OEBPS/text/page_1_01.xhtml").replace(
        "<p>نص ١</p>", f'<p><img src="{page_img_src}" alt="cover" /></p>'
    )
    _rewrite_zip_entry(source_epub, "OEBPS/text/page_1_01.xhtml", first_page)
    _rewrite_zip_entry(
        source_epub,
        asset_entry_name,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
    )
    source_opf = _read_zip_text(source_epub, opf_entry_name).replace(
        "</manifest>",
        f'<item id="cover" href="{manifest_asset_href}" media-type="image/svg+xml" /></manifest>',
    )
    _rewrite_zip_entry(source_epub, opf_entry_name, source_opf)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    for epub_path in written_files:
        with zipfile.ZipFile(epub_path) as zf:
            output_opf = zf.read("OEBPS/content.opf").decode()
            assert asset_entry_name in zf.namelist()
            assert f'href="{expected_manifest_href}"' in output_opf


def test_split_epub_by_volumes_handles_nav_with_custom_id(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("custom_nav.epub")

    _rename_zip_entries(source_epub, {"OEBPS/nav.xhtml": "OEBPS/toc.xhtml"})
    source_opf = _read_zip_text(source_epub, "OEBPS/content.opf")
    source_opf = source_opf.replace(
        'id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"',
        'id="toc" href="toc.xhtml" media-type="application/xhtml+xml" properties="nav"',
    )
    source_opf = source_opf.replace('<itemref idref="nav" />', '<itemref idref="toc" />')
    _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    output_opf = _read_zip_text(written_files[0], "OEBPS/content.opf")
    assert 'href="toc.xhtml"' not in output_opf
    assert '<itemref idref="nav" />' in output_opf


@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "source_styles.epub",
            "source_css": "body{background:#123;color:#fff}",
            "remove_stylesheet": False,
            "expected_css": "body{background:#123;color:#fff}",
        },
        {
            "name": "missing_styles.epub",
            "source_css": "",
            "remove_stylesheet": True,
            "expected_css": split_epub.BASE_CSS,
        },
    ],
    ids=["preserve-source", "fallback-default"],
)
def test_split_epub_by_volumes_stylesheet_handling(
    make_multi_volume_epub, tmp_path: Path, case: dict[str, str | bool]
) -> None:
    source_epub = make_multi_volume_epub(str(case["name"]))
    source_css = str(case["source_css"])
    if source_css:
        _rewrite_zip_entry(source_epub, "OEBPS/styles.css", source_css)
    if bool(case["remove_stylesheet"]):
        _remove_zip_entries(source_epub, {"OEBPS/styles.css"})
        source_opf = _read_zip_text(source_epub, "OEBPS/content.opf").replace(
            '<item id="css" href="styles.css" media-type="text/css" />', ""
        )
        _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    for epub_path in written_files:
        assert _read_zip_text(epub_path, "OEBPS/styles.css") == str(case["expected_css"])


def test_split_epub_by_volumes_handles_case_insensitive_source_page_paths(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("case_pages.epub")
    _rename_zip_entries(
        source_epub,
        {
            name: name.replace("OEBPS/text/", "OEBPS/Text/")
            for name in _list_text_pages(source_epub)
        },
    )

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "case_pages - 1.epub").exists()
    assert (tmp_path / "case_pages - 2.epub").exists()


def test_split_epub_by_volumes_handles_generic_text_filenames(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("generic_text_names.epub")
    old_pages = _list_text_pages(source_epub)
    rename_map = {
        old_name: f"OEBPS/text/chapter_{index:02}.xhtml"
        for index, old_name in enumerate(old_pages, start=1)
    }
    _rename_zip_entries(source_epub, rename_map)

    source_opf = _read_zip_text(source_epub, "OEBPS/content.opf")
    source_nav = _read_zip_text(source_epub, "OEBPS/nav.xhtml")
    source_ncx = _read_zip_text(source_epub, "OEBPS/toc.ncx")
    for old_name, new_name in rename_map.items():
        old_href = old_name.removeprefix("OEBPS/")
        new_href = new_name.removeprefix("OEBPS/")
        source_opf = source_opf.replace(f'href="{old_href}"', f'href="{new_href}"')
        source_nav = source_nav.replace(old_href, new_href)
        source_ncx = source_ncx.replace(old_href, new_href)
    _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)
    _rewrite_zip_entry(source_epub, "OEBPS/nav.xhtml", source_nav)
    _rewrite_zip_entry(source_epub, "OEBPS/toc.ncx", source_ncx)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "generic_text_names - 1.epub").exists()
    assert (tmp_path / "generic_text_names - 2.epub").exists()
    first_opf = _read_zip_text(tmp_path / "generic_text_names - 1.epub", "OEBPS/content.opf")
    assert "chapter_01.xhtml" not in first_opf


def test_split_epub_by_volumes_handles_spine_docs_outside_text_dir(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("xhtml_spine_docs.epub")
    old_pages = _list_text_pages(source_epub)
    rename_map = {
        old_name: f"OEBPS/xhtml/chapter_{index:02}.xhtml"
        for index, old_name in enumerate(old_pages, start=1)
    }
    _rename_zip_entries(source_epub, {**rename_map, "OEBPS/nav.xhtml": "OEBPS/toc/nav.xhtml"})

    source_opf = _read_zip_text(source_epub, "OEBPS/content.opf")
    source_nav = _read_zip_text(source_epub, "OEBPS/toc/nav.xhtml")
    source_ncx = _read_zip_text(source_epub, "OEBPS/toc.ncx")
    source_opf = source_opf.replace('href="nav.xhtml"', 'href="toc/nav.xhtml"')
    for old_name, new_name in rename_map.items():
        old_href = old_name.removeprefix("OEBPS/")
        new_href = new_name.removeprefix("OEBPS/")
        source_opf = source_opf.replace(f'href="{old_href}"', f'href="{new_href}"')
        source_nav = source_nav.replace(old_href, f"../{new_href}")
        source_ncx = source_ncx.replace(old_href, new_href)
    _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)
    _rewrite_zip_entry(source_epub, "OEBPS/toc/nav.xhtml", source_nav)
    _rewrite_zip_entry(source_epub, "OEBPS/toc.ncx", source_ncx)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "xhtml_spine_docs - 1.epub").exists()
    assert (tmp_path / "xhtml_spine_docs - 2.epub").exists()
    first_opf = _read_zip_text(tmp_path / "xhtml_spine_docs - 1.epub", "OEBPS/content.opf")
    assert "xhtml/chapter_01.xhtml" not in first_opf


@pytest.mark.parametrize(
    "case",
    [
        {
            "source_language": "en",
            "source_progression": "ltr",
            "expected_direction": "ltr",
            "expected_progression": "ltr",
        },
        {
            "source_language": "en",
            "source_progression": "",
            "expected_direction": "ltr",
            "expected_progression": "ltr",
        },
        {
            "source_language": "ar",
            "source_progression": "",
            "expected_direction": "rtl",
            "expected_progression": "rtl",
        },
    ],
    ids=["explicit-ltr", "lang-fallback-ltr", "lang-fallback-rtl"],
)
def test_split_epub_by_volumes_infers_direction_from_source_metadata(
    make_multi_volume_epub,
    tmp_path: Path,
    case: dict[str, str],
) -> None:
    source_language = case["source_language"]
    source_progression = case["source_progression"]
    expected_direction = case["expected_direction"]
    expected_progression = case["expected_progression"]

    source_epub = make_multi_volume_epub("direction.epub")
    source_opf = _read_zip_text(source_epub, "OEBPS/content.opf")
    source_opf = re.sub(
        r"<dc:language>.*?</dc:language>",
        f"<dc:language>{source_language}</dc:language>",
        source_opf,
        count=1,
    )
    if source_progression:
        source_opf = re.sub(
            r'page-progression-direction="[^"]+"',
            f'page-progression-direction="{source_progression}"',
            source_opf,
            count=1,
        )
    else:
        source_opf = re.sub(r'\s+page-progression-direction="[^"]+"', "", source_opf, count=1)
    _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    output_opf = _read_zip_text(written_files[0], "OEBPS/content.opf")
    output_info = _read_zip_text(written_files[0], "OEBPS/info.xhtml")
    assert f"<dc:language>{source_language}</dc:language>" in output_opf
    assert f'page-progression-direction="{expected_progression}"' in output_opf
    assert f'lang="{source_language}"' in output_info
    assert f'dir="{expected_direction}"' in output_info


def test_split_epub_by_volumes_handles_utf16_opf(make_multi_volume_epub, tmp_path: Path) -> None:
    source_epub = make_multi_volume_epub("utf16_opf.epub")
    source_opf = _read_zip_text(source_epub, "OEBPS/content.opf").replace(
        'encoding="utf-8"', 'encoding="utf-16"'
    )
    _rewrite_zip_entry_bytes(source_epub, "OEBPS/content.opf", source_opf.encode("utf-16"))

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES


@pytest.mark.parametrize(
    ("language", "expected_language", "expected_page", "expected_info", "expected_toc"),
    [
        ("", "en", "Page 1", "Book Info", "Table of Contents"),
        ("fr", "en", "Page 1", "Book Info", "Table of Contents"),
        ("ar", "ar", "صفحة 1", "بطاقة الكتاب", "فهرس الموضوعات"),
        ("ar-EG", "ar", "صفحة 1", "بطاقة الكتاب", "فهرس الموضوعات"),
    ],
    ids=["default-en", "unknown-fallback-en", "arabic", "arabic-regional"],
)
def test_build_epub_bytes_uses_language_specific_labels(
    language: str,
    expected_language: str,
    expected_page: str,
    expected_info: str,
    expected_toc: str,
) -> None:
    info = {
        "title": "",
        "author": "",
        "language": language,
        "about": "<p>about</p>",
        "toc": [],
    }
    pages = [{"page_number": 1, "page": 1, "text_html": "<p>x</p>"}]

    epub_bytes = split_epub._build_epub_bytes(info, pages, include_toc_page=True)

    output_opf = _read_zip_text_bytes(epub_bytes, "OEBPS/content.opf")
    output_nav = _read_zip_text_bytes(epub_bytes, "OEBPS/nav.xhtml")
    output_ncx = _read_zip_text_bytes(epub_bytes, "OEBPS/toc.ncx")
    output_info = _read_zip_text_bytes(epub_bytes, "OEBPS/info.xhtml")
    assert f"<dc:language>{expected_language}</dc:language>" in output_opf
    assert expected_page in output_nav
    assert expected_page in output_ncx
    assert expected_info in output_info
    assert expected_info in output_ncx
    assert expected_toc in output_nav
    assert expected_toc in output_ncx


def test_cut_toc_keeps_in_range_children_when_parent_is_before_start() -> None:
    toc = [
        ({"page": 1, "text": "مقدمة"}, [{"page": 50, "text": "باب"}, {"page": 70, "text": "خارج"}])
    ]

    trimmed = split_epub._cut_toc(toc, start_page=40, end_page=60)

    assert trimmed == [{"page": 50, "text": "باب"}]


def test_cut_toc_keeps_in_range_items_when_order_is_not_sorted() -> None:
    toc = [{"page": 80, "text": "خارج"}, {"page": 50, "text": "داخل"}]

    trimmed = split_epub._cut_toc(toc, start_page=40, end_page=60)

    assert trimmed == [{"page": 50, "text": "داخل"}]


def test_parse_nav_toc_prefers_nav_with_toc_type() -> None:
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        "<body>"
        '<nav epub:type="landmarks"><ol><li><a href="info.xhtml">بطاقة الكتاب</a></li></ol></nav>'
        '<nav epub:type="toc"><ol><li><a href="text/page_1_02.xhtml#chap-2">باب</a></li></ol></nav>'
        "</body>"
        "</html>"
    )

    parsed = split_epub._parse_nav_toc(nav_xhtml)

    assert parsed == [{"page": 2, "text": "باب", "anchor": "chap-2"}]


def test_parse_nav_toc_prefers_nav_with_toc_id_when_type_is_missing() -> None:
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<body>"
        '<nav role="doc-landmarks"><ol><li><a href="info.xhtml">بطاقة الكتاب</a></li></ol></nav>'
        '<nav id="toc"><ol><li><a href="text/page_1_02.xhtml#chap-2">باب</a></li></ol></nav>'
        "</body>"
        "</html>"
    )

    parsed = split_epub._parse_nav_toc(nav_xhtml)

    assert parsed == [{"page": 2, "text": "باب", "anchor": "chap-2"}]


def test_parse_nav_toc_keeps_unlinked_top_level_nodes() -> None:
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        "<body>"
        '<nav epub:type="toc"><ol>'
        "<li><span>الجزء الأول</span><ol>"
        '<li><a href="text/page_1_01.xhtml">أ</a></li><li><a href="text/page_1_02.xhtml">ب</a></li>'
        "</ol></li>"
        "<li><span>الجزء الثاني</span><ol>"
        '<li><a href="text/page_1_03.xhtml">ج</a></li><li><a href="text/page_1_04.xhtml">د</a></li>'
        "</ol></li>"
        "</ol></nav>"
        "</body>"
        "</html>"
    )

    parsed = split_epub._parse_nav_toc(nav_xhtml)

    assert isinstance(parsed[0], tuple)
    assert parsed[0][0]["text"] == "الجزء الأول"
    assert parsed[1][0]["text"] == "الجزء الثاني"


def test_parse_ncx_toc_keeps_unlinked_top_level_nodes() -> None:
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        "<navMap>"
        '<navPoint id="p1"><navLabel><text>الجزء الأول</text></navLabel>'
        '<navPoint id="c1"><navLabel><text>أ</text></navLabel><content src="text/page_1_01.xhtml"/></navPoint>'
        "</navPoint>"
        '<navPoint id="p2"><navLabel><text>الجزء الثاني</text></navLabel>'
        '<navPoint id="c2"><navLabel><text>ب</text></navLabel><content src="text/page_1_03.xhtml"/></navPoint>'
        "</navPoint>"
        "</navMap>"
        "</ncx>"
    )

    parsed = split_epub._parse_ncx_toc(ncx)

    assert isinstance(parsed[0], tuple)
    assert parsed[0][0]["text"] == "الجزء الأول"
    assert parsed[1][0]["text"] == "الجزء الثاني"


def test_split_epub_by_volumes_splits_by_unlinked_top_level_toc_nodes(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("unlinked_top_level.epub")
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        "<body>"
        '<nav epub:type="toc"><ol>'
        "<li><span>الجزء الأول</span><ol>"
        '<li><a href="text/page_1_01.xhtml">أ</a></li><li><a href="text/page_1_02.xhtml">ب</a></li>'
        "</ol></li>"
        "<li><span>الجزء الثاني</span><ol>"
        '<li><a href="text/page_1_03.xhtml">ج</a></li><li><a href="text/page_1_04.xhtml">د</a></li>'
        "</ol></li>"
        "</ol></nav>"
        "</body>"
        "</html>"
    )
    _rewrite_zip_entry(source_epub, "OEBPS/nav.xhtml", nav_xhtml)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    first = tmp_path / "unlinked_top_level - 1.epub"
    second = tmp_path / "unlinked_top_level - 2.epub"
    assert _list_text_pages(first) == ["OEBPS/text/page_1_01.xhtml", "OEBPS/text/page_1_02.xhtml"]
    assert _list_text_pages(second) == ["OEBPS/text/page_1_03.xhtml", "OEBPS/text/page_1_04.xhtml"]


def test_split_epub_by_volumes_parses_wrapped_top_level_links(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("wrapped_top_level_links.epub")
    nav_xhtml = _read_zip_text(source_epub, "OEBPS/nav.xhtml").replace(
        '<li><a href="text/page_1_03.xhtml#toc-2">القسم الثاني</a><ol>',
        '<li><p><a href="text/page_1_03.xhtml#toc-2">القسم الثاني</a></p><ol>',
    )
    _rewrite_zip_entry(source_epub, "OEBPS/nav.xhtml", nav_xhtml)
    _remove_zip_entries(source_epub, {"OEBPS/toc.ncx"})

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES


def test_split_epub_by_volumes_falls_back_to_ncx_when_nav_hrefs_are_unresolved(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("unresolved_nav_hrefs.epub")
    nav_xhtml = _read_zip_text(source_epub, "OEBPS/nav.xhtml")
    nav_xhtml = nav_xhtml.replace("text/page_1_01.xhtml#toc-1", "text/intro.xhtml#toc-1")
    nav_xhtml = nav_xhtml.replace("text/page_1_03.xhtml#toc-2", "text/part-two.xhtml#toc-2")
    nav_xhtml = nav_xhtml.replace("text/page_1_04.xhtml#toc-3", "text/part-two-detail.xhtml#toc-3")
    _rewrite_zip_entry(source_epub, "OEBPS/nav.xhtml", nav_xhtml)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "unresolved_nav_hrefs - 1.epub").exists()
    assert (tmp_path / "unresolved_nav_hrefs - 2.epub").exists()


def test_split_epub_by_volumes_falls_back_to_ncx_when_nav_is_partially_unresolved(
    make_multi_volume_epub, tmp_path: Path
) -> None:
    source_epub = make_multi_volume_epub("partially_unresolved_nav_hrefs.epub")
    nav_xhtml = _read_zip_text(source_epub, "OEBPS/nav.xhtml")
    nav_xhtml = nav_xhtml.replace("text/page_1_03.xhtml#toc-2", "text/part-two.xhtml#toc-2")
    nav_xhtml = nav_xhtml.replace("text/page_1_04.xhtml#toc-3", "text/part-two-detail.xhtml#toc-3")
    _rewrite_zip_entry(source_epub, "OEBPS/nav.xhtml", nav_xhtml)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / "partially_unresolved_nav_hrefs - 1.epub").exists()
    assert (tmp_path / "partially_unresolved_nav_hrefs - 2.epub").exists()


@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "nav_uppercase_links.epub",
            "new_nav_name": "OEBPS/nav.xhtml",
            "link_prefix": "Text/",
        },
        {
            "name": "nav_parent_relative_links.epub",
            "new_nav_name": "OEBPS/toc/nav.xhtml",
            "link_prefix": "../text/",
        },
    ],
    ids=["uppercase-links", "parent-relative-links"],
)
def test_split_epub_by_volumes_parses_nav_links_with_case_and_relative_prefixes(
    make_multi_volume_epub,
    tmp_path: Path,
    case: dict[str, str],
) -> None:
    source_epub = make_multi_volume_epub(case["name"])
    new_nav_name = case["new_nav_name"]
    link_prefix = case["link_prefix"]

    if new_nav_name != "OEBPS/nav.xhtml":
        _rename_zip_entries(source_epub, {"OEBPS/nav.xhtml": new_nav_name})
        source_opf = _read_zip_text(source_epub, "OEBPS/content.opf").replace(
            'href="nav.xhtml"', f'href="{new_nav_name.removeprefix("OEBPS/")}"'
        )
        _rewrite_zip_entry(source_epub, "OEBPS/content.opf", source_opf)

    nav_xhtml = _read_zip_text(source_epub, new_nav_name).replace("text/", link_prefix)
    _rewrite_zip_entry(source_epub, new_nav_name, nav_xhtml)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    assert (tmp_path / f"{Path(case['name']).stem} - 1.epub").exists()
    assert (tmp_path / f"{Path(case['name']).stem} - 2.epub").exists()


def test_split_epub_by_volumes_keeps_pages_before_first_toc_boundary(
    make_epub_from_payload, tmp_path: Path
) -> None:
    info = {
        "title": "كتاب",
        "author": "مؤلف",
        "about": "<p>نبذة</p>",
        "toc": [{"page": 2, "text": "الجزء الأول"}, {"page": 4, "text": "الجزء الثاني"}],
        "volumes": {},
        "page_chapters": {2: ["الجزء الأول"], 4: ["الجزء الثاني"]},
    }
    pages = [
        {"page_number": 1, "page": 1, "text_html": "<p>نص ١</p>"},
        {"page_number": 2, "page": 2, "text_html": "<p>نص ٢</p>"},
        {"page_number": 3, "page": 3, "text_html": "<p>نص ٣</p>"},
        {"page_number": 4, "page": 4, "text_html": "<p>نص ٤</p>"},
    ]
    source_epub = make_epub_from_payload("leading_pages.epub", info, pages)

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == EXPECTED_SPLIT_FILES
    first = tmp_path / "leading_pages - 1.epub"
    second = tmp_path / "leading_pages - 2.epub"
    assert _list_text_pages(first) == [
        "OEBPS/text/page_1_01.xhtml",
        "OEBPS/text/page_1_02.xhtml",
        "OEBPS/text/page_1_03.xhtml",
    ]
    assert _list_text_pages(second) == ["OEBPS/text/page_1_04.xhtml"]


@pytest.mark.parametrize(
    "case",
    [
        {
            "name": "broken_nav.epub",
            "entry_name": "OEBPS/nav.xhtml",
            "broken_content": '<html><body><nav><ol><li><a href="text/page_1_01.xhtml">x',
            "remove_ncx": True,
            "expected_count": 0,
        },
        {
            "name": "broken_nav_with_ncx.epub",
            "entry_name": "OEBPS/nav.xhtml",
            "broken_content": '<html><body><nav><ol><li><a href="text/page_1_01.xhtml">x',
            "remove_ncx": False,
            "expected_count": EXPECTED_SPLIT_FILES,
        },
        {
            "name": "broken_info.epub",
            "entry_name": "OEBPS/info.xhtml",
            "broken_content": "<html><body><p>broken",
            "remove_ncx": False,
            "expected_count": EXPECTED_SPLIT_FILES,
        },
    ],
    ids=["malformed-nav-no-ncx", "malformed-nav-with-ncx", "malformed-info"],
)
def test_split_epub_by_volumes_handles_malformed_metadata_pages(
    make_multi_volume_epub, tmp_path: Path, case: dict[str, str | int]
) -> None:
    source_epub = make_multi_volume_epub(str(case["name"]))
    if bool(case["remove_ncx"]):
        _remove_zip_entries(source_epub, {"OEBPS/toc.ncx"})
    _rewrite_zip_entry(source_epub, str(case["entry_name"]), str(case["broken_content"]))

    written_files = split_epub.split_epub_by_volumes(source_epub, tmp_path)

    assert len(written_files) == int(case["expected_count"])
