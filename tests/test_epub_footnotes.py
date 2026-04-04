# ruff: noqa: RUF001

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from ebook_converter_bot.utils.epub import standardize_epub_footnotes
from ebook_converter_bot.utils.epub_footnotes import pop_leading_continuation


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


def test_standardize_epub_footnotes_merges_continuation_across_placeholder_page(
    tmp_path: Path,
) -> None:
    epub_path = tmp_path / "book.epub"
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>t</dc:title>
  </metadata>
  <manifest>
    <item id="page_1" href="Text/page_1.xhtml" media-type="application/xhtml+xml"/>
    <item id="page_2" href="Text/page_2.xhtml" media-type="application/xhtml+xml"/>
    <item id="page_3" href="Text/page_3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="page_1"/>
    <itemref idref="page_2"/>
    <itemref idref="page_3"/>
  </spine>
</package>
"""
    with ZipFile(epub_path, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr(
            "OEBPS/Text/page_1.xhtml",
            _xhtml_document('<div><p>متن (١)</p><hr /><p class="hamesh">(١) هامش أول</p></div>'),
        )
        z.writestr("OEBPS/Text/page_2.xhtml", _xhtml_document("<div><p>. . .</p></div>"))
        z.writestr(
            "OEBPS/Text/page_3.xhtml",
            _xhtml_document(
                '<div><p>متن ثالث</p><hr /><p class="hamesh">=تكملة بعد صفحة فاصلة</p></div>'
            ),
        )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()
        page_3 = z.read("OEBPS/Text/page_3.xhtml").decode()

    assert "هامش أول" in page_1
    assert "تكملة بعد صفحة فاصلة" in page_1
    assert 'id="fn0"' not in page_3


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


def test_standardize_epub_footnotes_merges_numbered_sublines_in_continuation(
    tmp_path: Path,
) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>متن (١)</p><hr /><p class="hamesh">(١) بداية الحاشية =</p></div>',
        page_2_body=(
            '<div><p>. . .</p><hr /><p class="hamesh">= تتمة النص<br />١ - شاهد أول<br />٢ - شاهد ثان</p></div>'
        ),
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()
        page_2 = z.read("OEBPS/Text/page_2.xhtml").decode()

    assert "بداية الحاشية =" in page_1
    assert "تتمة النص" in page_1
    assert "١ - شاهد أول" in page_1
    assert "٢ - شاهد ثان" in page_1
    assert 'id="fn0"' not in page_2


def test_standardize_epub_footnotes_preserves_unlinked_numbered_sublines(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body=(
            '<div><p>متن (^١)</p><hr /><p class="hamesh">(^١) أصل الحاشية<br />١ - فرع أول<br />٢ - فرع ثان</p></div>'
        ),
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()

    assert "أصل الحاشية" in page_1
    assert "١ - فرع أول" in page_1
    assert "٢ - فرع ثان" in page_1
    assert '<aside id="fn1"' in page_1


def test_standardize_epub_footnotes_matches_by_number_not_position(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body=(
            '<div><p>مرجع (٨٠) ثم الحاشية (١)</p><hr /><p class="hamesh">(١) هذا هو الهامش الصحيح</p></div>'
        ),
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()

    assert "مرجع (٨٠)" in page_1
    assert ">(٨٠)</a>" not in page_1
    assert 'id="fnref1"' in page_1
    assert ">(١)</a>" in page_1
    assert "هذا هو الهامش الصحيح" in page_1


def test_standardize_epub_footnotes_links_caret_reference_inside_ayah(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>قال تعالى: ﴿والليل (^٢) إذا يغشى﴾.</p><hr /><p class="hamesh">(^٢) هامش</p></div>',
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()

    assert ">(^٢)</a>" in page_1
    assert '<aside id="fn1" epub:type="footnote">' in page_1


def test_standardize_epub_footnotes_links_non_caret_reference_inside_ayah_when_needed(
    tmp_path: Path,
) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body='<div><p>قال تعالى: ﴿والليل (٢) إذا يغشى﴾.</p><hr /><p class="hamesh">(٢) هامش</p></div>',
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()

    assert ">(٢)</a>" in page_1
    assert '<aside id="fn1" epub:type="footnote">' in page_1


def test_standardize_epub_footnotes_skips_ayah_number_before_closing_marker(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _create_epub(
        epub_path,
        page_1_body=(
            "<div><p>يكف بربك أنه على كل شيء شهيد (٥٣)﴾، فهذا استدلال (^١) بكمال ربوبيته.</p>"
            '<hr /><p class="hamesh">(^١) هذا أول هامش صحيح</p></div>'
        ),
    )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()

    assert "شهيد (٥٣)﴾" in page_1
    assert ">(٥٣)</a>" not in page_1
    assert 'id="fnref1"' in page_1
    assert ">(^١)</a>" in page_1
    assert '<aside id="fn1" epub:type="footnote">' in page_1
    assert "هذا أول هامش صحيح" in page_1


def test_standardize_epub_footnotes_merges_multiple_continuation_pages(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>t</dc:title>
  </metadata>
  <manifest>
    <item id="page_1" href="Text/page_1.xhtml" media-type="application/xhtml+xml"/>
    <item id="page_2" href="Text/page_2.xhtml" media-type="application/xhtml+xml"/>
    <item id="page_3" href="Text/page_3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="page_1"/>
    <itemref idref="page_2"/>
    <itemref idref="page_3"/>
  </spine>
</package>
"""
    with ZipFile(epub_path, "w", compression=ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr(
            "OEBPS/Text/page_1.xhtml",
            _xhtml_document('<div><p>متن (١)</p><hr /><p class="hamesh">(١) أصل الحاشية</p></div>'),
        )
        z.writestr(
            "OEBPS/Text/page_2.xhtml",
            _xhtml_document('<div><p>. . .</p><hr /><p class="hamesh">=تكملة أولى</p></div>'),
        )
        z.writestr(
            "OEBPS/Text/page_3.xhtml",
            _xhtml_document('<div><p>. . .</p><hr /><p class="hamesh">=تكملة ثانية</p></div>'),
        )

    assert standardize_epub_footnotes(epub_path) is True

    with ZipFile(epub_path, "r") as z:
        page_1 = z.read("OEBPS/Text/page_1.xhtml").decode()
        page_2 = z.read("OEBPS/Text/page_2.xhtml").decode()
        page_3 = z.read("OEBPS/Text/page_3.xhtml").decode()

    assert "أصل الحاشية" in page_1
    assert "تكملة أولى" in page_1
    assert "تكملة ثانية" in page_1
    assert 'id="fn0"' not in page_2
    assert 'id="fn0"' not in page_3


def test_pop_leading_continuation_handles_namespaced_hamesh() -> None:
    html_fragment = (
        '<html:div xmlns:html="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" class="hamesh">'
        '<aside id="fn0" epub:type="footnote"><span>= متابعة</span></aside>'
        '<aside id="fn1" epub:type="footnote"><a href="#fnref1" class="nu">(^١)</a><span> هامش</span></aside>'
        "</html:div>"
    )

    stripped, continuation = pop_leading_continuation(html_fragment)

    assert continuation == "متابعة"
    assert 'id="fn0"' not in stripped
    assert 'id="fn1"' in stripped


def test_pop_leading_continuation_works_without_hamesh_class() -> None:
    html_fragment = (
        '<section xmlns:epub="http://www.idpf.org/2007/ops">'
        '<aside id="fn0" epub:type="footnote"><span>= تكملة النص</span></aside>'
        '<aside id="fn1" epub:type="footnote"><span>هامش ١</span></aside>'
        "</section>"
    )

    stripped, continuation = pop_leading_continuation(html_fragment)

    assert continuation == "تكملة النص"
    assert 'id="fn0"' not in stripped
    assert 'id="fn1"' in stripped


def test_pop_leading_continuation_skips_non_continuation_fn0() -> None:
    html_fragment = (
        '<div xmlns:epub="http://www.idpf.org/2007/ops" class="hamesh">'
        '<aside id="fn0" epub:type="footnote"><span>هذا هامش عادي</span></aside>'
        '<aside id="fn1" epub:type="footnote"><span>هامش ١</span></aside>'
        "</div>"
    )

    stripped, continuation = pop_leading_continuation(html_fragment)

    assert continuation is None
    assert stripped == html_fragment
