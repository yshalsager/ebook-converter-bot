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
