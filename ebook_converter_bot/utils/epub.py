import re
from pathlib import Path
from typing import cast
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import html
from lxml.etree import Element, ElementTree, ParseError, XMLParser, fromstring, tostring

xml_parser = XMLParser(resolve_entities=False)


def set_epub_to_rtl(input_file: Path) -> bool:
    with ZipFile(input_file, "a", compression=ZIP_DEFLATED) as epub_book:
        content_opf: ZipInfo = list(
            filter(lambda x: x.filename.endswith(".opf"), epub_book.infolist())
        ).pop()
        opf_file_content = epub_book.read(content_opf.filename).decode()
        if match := re.search(r'<spine\s+[^>]*toc="ncx"[^>]*>', opf_file_content):
            spine_element = match.group(0)
            if "rtl" not in spine_element:
                new_opf_file_content = re.sub(
                    r'<spine\s+[^>]*toc="ncx"',
                    r'<spine page-progression-direction="rtl" toc="ncx"',
                    opf_file_content,
                )
                with epub_book.open(content_opf.filename, "w") as o:
                    o.write(new_opf_file_content.encode())
                # Add * { direction: rtl !important; } to css files
                css_files = list(
                    filter(lambda x: x.filename.endswith(".css"), epub_book.infolist())
                )
                for css_file in css_files:
                    css_content = epub_book.read(css_file)
                    new_css_content = (
                        f"* {{direction: rtl !important;}}\n{css_content.decode()}"
                    )
                    with epub_book.open(css_file.filename, "w") as o:
                        o.write(new_css_content.encode())
                return True
        return False


def fix_content_opf_problems(input_file: Path) -> None:
    with ZipFile(input_file, "a", compression=ZIP_DEFLATED) as epub_book:
        content_opf = list(
            filter(lambda x: x.filename.endswith(".opf"), epub_book.infolist())
        ).pop()
        opf_file_content = epub_book.read(content_opf.filename).decode()
        manifest_wrong_list_pos = opf_file_content.find('<item id="page_1"')
        manifest_correct_list_pos = opf_file_content.rfind('<item id="page_1"')
        manifest_end_pos = opf_file_content.find("</manifest>")
        spine_line_match = re.search(r"<spine .*\n", opf_file_content)
        assert spine_line_match is not None
        spine_line = spine_line_match.group(0)
        spine_correct_list_pos = opf_file_content.rfind('<itemref idref="page_1"')
        new_content = (
            opf_file_content[:manifest_wrong_list_pos]
            + opf_file_content[manifest_correct_list_pos:manifest_end_pos]
            + "</manifest>"
            + spine_line
            + opf_file_content[spine_correct_list_pos:]
        )
        # Fix missing text content exists in content.opf
        try:
            zip_text_contents = [
                i.get("href").split("/")[-1]
                for i in fromstring(new_content.encode(), xml_parser)[1]  # noqa: S320
                if "Text" in i.get("href")
            ]
            real_text_contents = [
                i.split("/")[-1] for i in epub_book.namelist() if "Text" in i
            ]
            missing_text_content = list(
                set(zip_text_contents) - set(real_text_contents)
            )
            for item in missing_text_content:
                new_content = re.sub(f'<item .*{item}".*\n', "", new_content)
        except ParseError:
            pass
        with epub_book.open(content_opf.filename, "w") as o:
            o.write(new_content.encode())


def _flatten_ncx_toc(nav_map: Element, namespace: str) -> list[Element]:
    flattened_items: list[Element] = []

    def traverse_nav_point(nav_point: Element, play_order: int) -> None:
        # Create a new navPoint element with updated attributes
        new_nav_point = Element(
            "navPoint", {"id": f"num_{play_order}", "playOrder": str(play_order)}
        )
        # Copy the child elements (navLabel and content) from the original navPoint to the new one
        for child in nav_point:
            if child.tag != f"{namespace}navPoint":
                new_nav_point.append(child)
        # Add the new item
        flattened_items.append(new_nav_point)

        # Recursively traverse nested navPoints
        for child in nav_point:
            if child.tag == f"{namespace}navPoint":
                play_order += 1
                traverse_nav_point(child, play_order)

    for idx, navigation_point in enumerate(nav_map, start=1):
        traverse_nav_point(navigation_point, idx)

    return flattened_items


def _flatten_html_nav(html_nav_file: bytes) -> bytes:
    root = html.fromstring(html_nav_file)
    nested_ol_elems = root.xpath(".//*/ol/*/ol")
    # Flatten the nested lists
    for nested_ol in nested_ol_elems:
        parent_li = nested_ol.getparent()
        parent_ol = parent_li.getparent()
        index = parent_ol.index(parent_li)
        parent_ol.remove(parent_li)
        for li in reversed(nested_ol):
            parent_ol.insert(index, li)
        nested_ol.drop_tree()
    return cast(bytes, tostring(root, encoding="utf-8"))


def flatten_toc(input_file: Path) -> None:
    with ZipFile(input_file, "a", compression=ZIP_DEFLATED) as epub_book:
        # Flatten toc.ncx
        toc_files = list(
            filter(lambda x: x.filename.endswith("toc.ncx"), epub_book.infolist())
        )
        if not toc_files:
            return
        toc_ncx = toc_files.pop()
        toc_xml: ElementTree = ElementTree(
            fromstring(epub_book.read(toc_ncx.filename), xml_parser)  # noqa: S320
        )
        root: Element = toc_xml.getroot()
        namespace = root.tag.split("}")[0] + "}"
        nav_map: Element = toc_xml.find(f".//{namespace}navMap")
        new_toc = _flatten_ncx_toc(nav_map, namespace)
        root.remove(nav_map)
        new_nav_map = Element("navMap")
        for i in new_toc:
            new_nav_map.append(i)
        root.append(new_nav_map)
        # print(tostring(root, encoding="utf-8").decode('utf-8'))
        with epub_book.open(toc_ncx.filename, "w") as o:
            o.write(tostring(toc_xml, encoding="utf-8"))

        # Flatten nav.xhtml
        nav_html_files = list(
            filter(lambda x: x.filename.endswith("nav.xhtml"), epub_book.infolist())
        )
        if not nav_html_files:
            return
        nav_html = nav_html_files.pop()
        new_nav_html = _flatten_html_nav(epub_book.read(nav_html.filename))
        with epub_book.open(nav_html.filename, "w") as o:
            o.write(new_nav_html)


if __name__ == "__main__":
    from sys import argv

    flatten_toc(Path(argv[1]))
