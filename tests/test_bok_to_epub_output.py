import re
from pathlib import Path
from zipfile import ZipFile

from ebook_converter_bot.utils.bok_to_epub import EpubBook, write_epub
from ebook_converter_bot.utils.epub import xml_parser
from lxml import etree, html


def _sample_book() -> EpubBook:
    return EpubBook(
        title="اختبار",
        author="كاتب",
        about="<div><h1>اختبار</h1></div>",
        pages=[
            {
                "page_number": 1,
                "page": 1,
                "part": 1,
                "text_html": "<div><p>نص الصفحة</p></div>",
            }
        ],
        toc_tree=[{"text": "المقدمة", "page": 1, "anchor": ""}],
    )


def test_write_epub_outputs_valid_metadata_and_css(tmp_path: Path) -> None:
    out = tmp_path / "book.epub"
    write_epub(out, _sample_book(), include_toc_page=False)

    with ZipFile(out, "r") as z:
        opf_root = etree.fromstring(z.read("OEBPS/content.opf"), xml_parser)
        opf_ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}

        identifier = opf_root.xpath("string(//dc:identifier[@id='bookid'])", namespaces=opf_ns)
        modified = opf_root.xpath(
            "string(//opf:meta[@property='dcterms:modified'])", namespaces=opf_ns
        )
        assert identifier == "urn:shamela_bok:0"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", modified)

        ncx_root = etree.fromstring(z.read("OEBPS/toc.ncx"), xml_parser)
        ncx_ns = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
        uid = ncx_root.xpath(
            "string(//ncx:head/ncx:meta[@name='dtb:uid']/@content)", namespaces=ncx_ns
        )
        assert uid == identifier

        css_text = z.read("OEBPS/styles.css").decode("utf-8")
        assert "direction:" not in css_text


def test_write_epub_toc_links_only_to_spine_pages(tmp_path: Path) -> None:
    out = tmp_path / "book.epub"
    write_epub(out, _sample_book(), include_toc_page=False)

    with ZipFile(out, "r") as z:
        opf_root = etree.fromstring(z.read("OEBPS/content.opf"), xml_parser)
        opf_ns = {"opf": "http://www.idpf.org/2007/opf"}

        manifest = {
            item.get("id"): item.get("href")
            for item in opf_root.xpath("//opf:manifest/opf:item", namespaces=opf_ns)
        }
        spine_refs = [
            itemref.get("idref")
            for itemref in opf_root.xpath("//opf:spine/opf:itemref", namespaces=opf_ns)
        ]
        spine_hrefs = {manifest[idref] for idref in spine_refs if idref in manifest}

        nav_doc = html.fromstring(z.read("OEBPS/nav.xhtml"))
        nav_links = nav_doc.xpath(
            "//*[local-name()='nav' and @epub:type='toc']//*[local-name()='a']/@href",
            namespaces={"epub": "http://www.idpf.org/2007/ops"},
        )
        for href in nav_links:
            target = href.split("#", 1)[0]
            assert target in spine_hrefs

        ncx_root = etree.fromstring(z.read("OEBPS/toc.ncx"), xml_parser)
        ncx_ns = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
        ncx_targets = ncx_root.xpath(
            "//ncx:navMap/ncx:navPoint/ncx:content/@src", namespaces=ncx_ns
        )
        for src in ncx_targets:
            target = src.split("#", 1)[0]
            assert target in spine_hrefs
