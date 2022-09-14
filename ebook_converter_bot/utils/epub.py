import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from ebooklib import epub


def set_epub_to_rtl(input_file) -> bool:
    try:
        book = epub.read_epub(input_file)
        if book.direction != "rtl":
            book.direction = "rtl"
            epub.write_epub(input_file, book)
            return True
    except KeyError:
        return False


def fix_content_opf_problems(input_file):
    with ZipFile(input_file) as book, ZipFile(
        f"{input_file}_", "w", compression=ZIP_DEFLATED
    ) as out:
        for file in book.infolist():
            with book.open(file) as infile:
                # Fix content.opf has duplicate entries
                if file.filename.endswith("content.opf"):
                    content = infile.read().decode()
                    manifest_wrong_list_pos = content.find('<item id="page_1"')
                    manifest_correct_list_pos = content.rfind('<item id="page_1"')
                    manifest_end_pos = content.find("</manifest>")
                    spine_line = re.search(r"<spine .*\n", content).group(0)
                    spine_correct_list_pos = content.rfind('<itemref idref="page_1"')
                    new_content = (
                        content[:manifest_wrong_list_pos]
                        + content[manifest_correct_list_pos:manifest_end_pos]
                        + "</manifest>"
                        + spine_line
                        + content[spine_correct_list_pos:]
                    )
                    # Fix missing text content exists in content.opf
                    try:
                        zip_text_contents = [
                            i.get("href").split("/")[-1]
                            for i in ElementTree.fromstring(new_content)[1]
                            if "Text" in i.get("href")
                        ]
                        real_text_contents = [
                            i.split("/")[-1] for i in book.namelist() if "Text" in i
                        ]
                        missing_text_content = list(
                            set(zip_text_contents) - set(real_text_contents)
                        )
                        for item in missing_text_content:
                            new_content = re.sub(
                                f'<item .*{item}".*\n', "", new_content
                            )
                    except ElementTree.ParseError:
                        continue
                    out.writestr(file.filename, new_content)
                else:
                    out.writestr(file, book.read(file.filename))

    Path(f"{input_file}_").rename(input_file)
