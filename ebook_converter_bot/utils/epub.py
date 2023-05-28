import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from defusedxml import ElementTree


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
                for i in ElementTree.fromstring(new_content)[1]
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
        except ElementTree.ParseError:
            pass
        with epub_book.open(content_opf.filename, "w") as o:
            o.write(new_content.encode())
