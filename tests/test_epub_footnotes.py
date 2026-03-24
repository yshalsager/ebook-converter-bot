# ruff: noqa: RUF001

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from ebook_converter_bot.utils.epub import standardize_epub_footnotes


def _xhtml_document(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<body>{body}</body></html>"
    )


def _create_epub(
    path: Path,
    *,
    page_1_body: str,
    page_2_body: str | None = None,
) -> None:
    manifest_items = [
        '<item id="page_1" href="Text/page_1.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine_items = ['<itemref idref="page_1"/>']
    if page_2_body is not None:
        manifest_items.append(
            '<item id="page_2" href="Text/page_2.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append('<itemref idref="page_2"/>')

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>t</dc:title>
  </metadata>
  <manifest>
    {"".join(manifest_items)}
  </manifest>
  <spine toc="ncx">
    {"".join(spine_items)}
  </spine>
</package>
"""

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/Text/page_1.xhtml", _xhtml_document(page_1_body))
        if page_2_body is not None:
            z.writestr("OEBPS/Text/page_2.xhtml", _xhtml_document(page_2_body))


def test_standardize_epub_footnotes_merges_cross_page_continuation(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>متن (١)</p><hr /><p class="hamesh">(١) هامش أول</p></div>',
        page_2_body='<div><p>متن ثان</p><hr /><p class="hamesh">=تكملة<br />سطر ثان</p></div>',
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()
        page_2 = z.read("OEBPS/Text/page_2.xhtml").decode()

    assert 'id="fnref1"' in page_1
    assert '<aside id="fn1" epub:type="footnote">' in page_1
    assert "هامش أول" in page_1
    assert "تكملة" in page_1
    assert "سطر ثان" in page_1
    assert '<aside id="fn0"' not in page_2
    assert "تكملة" not in page_2


def test_standardize_epub_footnotes_is_idempotent(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>متن [١]</p><hr /><p class="hamesh">[١] هامش أول</p></div>',
    )

    assert standardize_epub_footnotes(epub_path) is True
    after_first = epub_path.read_bytes()
    assert standardize_epub_footnotes(epub_path) is False
    assert epub_path.read_bytes() == after_first


def test_standardize_epub_footnotes_keeps_unparseable_hamesh_unchanged(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>متن (١)</p><hr /><p class="hamesh">التخريج: بلا ترقيم</p></div>',
    )

    before = epub_path.read_bytes()
    assert standardize_epub_footnotes(epub_path) is False
    assert epub_path.read_bytes() == before
