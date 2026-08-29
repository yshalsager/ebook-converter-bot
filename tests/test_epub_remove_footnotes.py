# ruff: noqa: RUF001

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from ebook_converter_bot.utils.epub import remove_epub_footnotes


def _create_epub(path: Path, *bodies: str) -> None:
    manifest = "".join(
        f'<item id="page_{index}" href="Text/page_{index}.xhtml" media-type="application/xhtml+xml"/>'
        for index in range(1, len(bodies) + 1)
    )
    spine = "".join(f'<itemref idref="page_{index}"/>' for index in range(1, len(bodies) + 1))
    opf = f"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<metadata/><manifest>{manifest}</manifest><spine>{spine}</spine></package>"""
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as book:
        book.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        book.writestr("OEBPS/content.opf", opf)
        for index, body in enumerate(bodies, 1):
            book.writestr(
                f"OEBPS/Text/page_{index}.xhtml",
                '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
                '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:epub="http://www.idpf.org/2007/ops">'
                f"<body>{body}</body></html>",
            )


def _pages(path: Path) -> list[str]:
    with ZipFile(path) as book:
        assert book.getinfo("mimetype").compress_type == ZIP_STORED
        return [
            book.read(name).decode()
            for name in sorted(name for name in book.namelist() if name.endswith(".xhtml"))
        ]


@pytest.mark.parametrize("keep_markers", [True, False])
def test_remove_epub_footnotes_handles_semantic_notes_and_endnotes(
    tmp_path: Path, *, keep_markers: bool
) -> None:
    path = tmp_path / "book.epub"
    _create_epub(
        path,
        '<p>قبل <sup><a id="ref1" href="#fn1" epub:type="noteref pagebreak" '
        'role="doc-noteref">١</a></sup> بعد <a href="#ordinary">رابط</a></p>'
        '<aside id="fn1" epub:type="footnote" role="doc-footnote">هامش أول</aside>'
        '<p>نهاية <a href="#endnotes" role="doc-noteref">٢</a></p>'
        '<section id="endnotes" epub:type="endnotes" role="doc-endnotes">هامش أخير</section>'
        '<aside class="note">ملاحظة عادية</aside><p><sup>٥٣</sup></p>',
    )

    assert remove_epub_footnotes(path, keep_markers=keep_markers) is True
    page = _pages(path)[0]

    assert "هامش أول" not in page
    assert "هامش أخير" not in page
    assert 'href="#ordinary"' in page
    assert "ملاحظة عادية" in page
    assert "٥٣" in page
    assert "doc-noteref" not in page
    assert 'epub:type="noteref' not in page
    if keep_markers:
        assert ">١</a>" in page
        assert ">٢</a>" in page
        assert 'epub:type="pagebreak"' in page
    else:
        assert ">١</a>" not in page
        assert ">٢</a>" not in page
        assert "<sup/>" not in page
        assert "قبل  بعد" in page

    first_result = path.read_bytes()
    assert remove_epub_footnotes(path, keep_markers=keep_markers) is False
    assert path.read_bytes() == first_result


def test_remove_epub_footnotes_normalizes_and_removes_multi_page_legacy_notes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "book.epub"
    _create_epub(
        path,
        '<div><p>متن (^١)</p><hr/><p class="hamesh">(^١) هامش =</p></div>',
        '<div><p>متن ثان</p><hr/><p class="hamesh">= تكملة الهامش</p></div>',
    )

    assert remove_epub_footnotes(path, keep_markers=False) is True
    pages = _pages(path)

    assert "هامش" not in "".join(pages)
    assert "(^١)" not in "".join(pages)
    assert "متن" in pages[0]
    assert "متن ثان" in pages[1]
    assert 'class="hamesh"' not in "".join(pages)

    first_result = path.read_bytes()
    assert remove_epub_footnotes(path, keep_markers=False) is False
    assert path.read_bytes() == first_result


@pytest.mark.parametrize("keep_markers", [True, False])
def test_remove_epub_footnotes_handles_guillemet_references(
    tmp_path: Path, *, keep_markers: bool
) -> None:
    path = tmp_path / "book.epub"
    _create_epub(
        path,
        '<p>متن «١» ثم «٢» ثم «٣» ثم «٤»</p><hr/><p class="hamesh">'
        "(١) هامش<br/>. (٢- ٣) هامش مشترك<br/>[.....] (٤) هامش</p>",
    )

    assert remove_epub_footnotes(path, keep_markers=keep_markers) is True
    page = _pages(path)[0]

    assert 'class="hamesh"' not in page
    assert all((marker in page) is keep_markers for marker in ("«١»", "«٢»", "«٣»", "«٤»"))


def test_remove_epub_footnotes_removes_unlinked_hamesh(tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    _create_epub(path, '<p>متن</p><hr/><p class="hamesh">تكملة بلا علامة</p>')

    assert remove_epub_footnotes(path, keep_markers=True) is True
    page = _pages(path)[0]

    assert "تكملة بلا علامة" not in page
    assert "<hr" not in page


@pytest.mark.parametrize(
    ("body", "keep_markers"),
    [
        (
            (
                '<p>متن <sup><a href="#fn1" id="ref1">(1)</a></sup>'
                '<a class="footn" href="#missing">(2)</a></p>'
                '<div class="clear">&nbsp;</div>'
                '<div class="footnote"><sup><a href="#ref1" id="fn1">(1)</a></sup> هامش</div>'
            ),
            True,
        ),
        ('متن (1)<br/><span class="footnote">(1) هامش</span>', False),
    ],
)
def test_remove_epub_footnotes_handles_legacy_footnote_classes(
    tmp_path: Path, body: str, *, keep_markers: bool
) -> None:
    path = tmp_path / "book.epub"
    _create_epub(path, f"<div>{body}</div>")

    assert remove_epub_footnotes(path, keep_markers=keep_markers) is True
    page = _pages(path)[0]

    assert "هامش" not in page
    assert "<!DOCTYPE html" in page
    assert 'href="#fn1"' not in page
    assert 'href="#missing"' not in page
    assert ("(1)" in page) is keep_markers
