from pathlib import Path
from time import monotonic

from ebook_converter_bot.utils.converter_options import (
    ConversionRequestState,
    build_options_keyboard,
    cleanup_expired_requests,
    format_button_rows,
    set_request_option,
)
from telethon.tl.types import KeyboardButtonCallback

LABELS = {
    "force_rtl_label": "Force RTL",
    "compress_cover_label": "Compress cover",
    "fix_epub_label": "Fix EPUB before converting",
    "flat_toc_label": "Flatten EPUB TOC",
    "smarten_punctuation_label": "Smarten punctuation",
    "change_justification_label": "Text justification",
    "remove_paragraph_spacing_label": "Remove paragraph spacing",
    "original_label": "Original",
    "left_label": "Left",
    "justify_label": "Justify",
    "docx_page_size_label": "DOCX page size",
    "docx_no_toc_label": "DOCX: disable generated TOC",
    "epub_version_label": "EPUB version",
    "epub_inline_toc_label": "EPUB: inline TOC",
    "epub_remove_background_label": "Remove EPUB background",
    "epub_split_volumes_label": "Split EPUB volumes",
    "epub_standardize_footnotes_label": "Standardize EPUB footnotes",
    "pdf_paper_size_label": "PDF paper size",
    "pdf_page_numbers_label": "PDF: page numbers",
    "kfx_doc_type_label": "KFX doc type",
    "kfx_pages_label": "KFX pages",
    "default_label": "Default",
    "letter_label": "Letter",
    "a4_label": "A4",
    "none_label": "None",
    "auto_label": "Auto",
    "pdoc_label": "PDOC",
    "ebok_label": "EBOK",
    "reset_options_label": "Reset options",
    "back_to_formats_label": "Back to formats",
    "cancel_label": "Cancel",
}


def _flatten_data(rows: list[list[KeyboardButtonCallback]]) -> list[bytes]:
    return [button.data for row in rows for button in row]


def test_format_button_rows_are_chunked_to_three() -> None:
    rows: list[list[KeyboardButtonCallback]] = format_button_rows(
        "12345678",
        ["azw3", "docx", "epub", "fb2", "htmlz", "kepub", "kfx"],
    )
    assert [len(row) for row in rows] == [3, 3, 1]
    assert rows[0][0].text == "🔸 azw3"
    assert rows[0][0].data == b"fmt|azw3|12345678"
    assert rows[1][2].text == "kepub"


def test_options_keyboard_context_tabs_and_docx_controls() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.epub",  # noqa: S108
        queued_at=monotonic(),
        input_ext="epub",
        options_context="docx",
    )
    rows = build_options_keyboard("12345678", state, LABELS)

    assert [button.data for button in rows[0]] == [
        b"ctx|docx|12345678",
        b"ctx|epub|12345678",
        b"ctx|pdf|12345678",
        b"ctx|kfx|12345678",
    ]
    assert rows[0][0].text.startswith("▸ DOCX")

    data = _flatten_data(rows)
    assert b"opt|compress_cover|1|12345678" in data
    assert b"opt|docx_page_size|default|12345678" in data
    assert b"opt|docx_page_size|letter|12345678" in data
    assert b"opt|docx_page_size|a4|12345678" in data
    assert b"opt|docx_no_toc|1|12345678" in data
    assert b"opt|epub_version|default|12345678" not in data
    assert b"opt|pdf_paper_size|default|12345678" not in data
    assert b"opt|kfx_doc_type|doc|12345678" not in data
    assert b"opt|fix_epub|1|12345678" in data
    assert b"opt|flat_toc|1|12345678" in data
    assert b"opt|epub_standardize_footnotes|1|12345678" in data
    assert [button.data for button in rows[-2]] == [b"opt|reset|1|12345678"]
    assert [button.data for button in rows[-1]] == [
        b"view|formats|12345678",
        b"cancel|12345678",
    ]


def test_options_keyboard_shows_selected_context_controls_only() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.pdf",  # noqa: S108
        queued_at=monotonic(),
        input_ext="pdf",
        options_context="pdf",
    )
    rows = build_options_keyboard("12345678", state, LABELS)
    data = _flatten_data(rows)

    assert rows[0][2].text.startswith("▸ PDF")
    assert b"opt|pdf_paper_size|default|12345678" in data
    assert b"opt|pdf_page_numbers|1|12345678" in data
    assert b"opt|docx_page_size|default|12345678" not in data
    assert b"opt|epub_version|default|12345678" not in data
    assert b"opt|kfx_doc_type|doc|12345678" not in data
    assert b"opt|fix_epub|1|12345678" not in data


def test_options_keyboard_epub_context_has_remove_background_toggle() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.epub",  # noqa: S108
        queued_at=monotonic(),
        input_ext="epub",
        options_context="epub",
    )
    rows = build_options_keyboard("12345678", state, LABELS)
    data = _flatten_data(rows)

    assert b"opt|epub_inline_toc|1|12345678" in data
    assert b"opt|epub_remove_background|1|12345678" in data
    assert b"opt|epub_split_volumes|1|12345678" in data


def test_options_keyboard_epub_context_hides_epub_only_toggles_for_non_epub_input() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.pdf",  # noqa: S108
        queued_at=monotonic(),
        input_ext="pdf",
        options_context="epub",
    )
    rows = build_options_keyboard("12345678", state, LABELS)
    data = _flatten_data(rows)

    assert b"opt|epub_inline_toc|1|12345678" in data
    assert b"opt|epub_remove_background|1|12345678" in data
    assert b"opt|epub_split_volumes|1|12345678" not in data


def test_options_keyboard_kfx_pages_none_and_auto_only() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.mobi",  # noqa: S108
        queued_at=monotonic(),
        input_ext="mobi",
        options_context="kfx",
    )
    rows = build_options_keyboard("12345678", state, LABELS)
    data = _flatten_data(rows)

    assert b"opt|kfx_pages|none|12345678" in data
    assert b"opt|kfx_pages|auto|12345678" in data
    assert all(b"opt|kfx_pages|200|" not in item for item in data)


def test_set_request_option_mutates_only_selected_flag() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.epub",  # noqa: S108
        queued_at=monotonic(),
        input_ext="epub",
    )

    assert set_request_option(state, "smarten", "1") is True
    assert state.smarten_punctuation is True
    assert state.remove_paragraph_spacing is False

    assert set_request_option(state, "compress_cover", "1") is True
    assert state.compress_cover is True

    assert set_request_option(state, "change_justification", "left") is True
    assert state.change_justification == "left"
    assert state.docx_page_size == "default"

    assert set_request_option(state, "docx_page_size", "a4") is True
    assert state.docx_page_size == "a4"
    assert state.epub_version == "default"

    assert set_request_option(state, "epub_version", "3") is True
    assert state.epub_version == "3"
    assert set_request_option(state, "epub_remove_background", "1") is True
    assert state.epub_remove_background is True
    assert set_request_option(state, "epub_split_volumes", "1") is True
    assert state.epub_split_volumes is True
    assert set_request_option(state, "epub_standardize_footnotes", "1") is True
    assert state.epub_standardize_footnotes is True
    assert state.pdf_paper_size == "default"

    assert set_request_option(state, "pdf_paper_size", "letter") is True
    assert state.pdf_paper_size == "letter"


def test_set_request_option_is_idempotent_and_validates_values() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.epub",  # noqa: S108
        queued_at=monotonic(),
        input_ext="epub",
    )

    assert set_request_option(state, "rtl", "1") is True
    assert set_request_option(state, "rtl", "1") is True
    assert state.force_rtl is True

    assert set_request_option(state, "kfx_pages", "none") is True
    assert state.kfx_pages is None
    assert set_request_option(state, "kfx_pages", "auto") is True
    assert state.kfx_pages == 0

    assert set_request_option(state, "epub_version", "4") is False
    assert set_request_option(state, "docx_page_size", "legal") is False


def test_set_request_option_reset_clears_all_options() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.epub",  # noqa: S108
        queued_at=monotonic(),
        input_ext="epub",
        force_rtl=True,
        compress_cover=True,
        fix_epub=True,
        flat_toc=True,
        smarten_punctuation=True,
        change_justification="justify",
        remove_paragraph_spacing=True,
        kfx_doc_type="book",
        kfx_pages=0,
        docx_page_size="a4",
        docx_no_toc=True,
        epub_version="3",
        epub_inline_toc=True,
        epub_remove_background=True,
        epub_split_volumes=True,
        epub_standardize_footnotes=True,
        pdf_paper_size="letter",
        pdf_page_numbers=True,
    )

    assert set_request_option(state, "reset", "1") is True
    assert state.force_rtl is False
    assert state.compress_cover is False
    assert state.fix_epub is False
    assert state.flat_toc is False
    assert state.smarten_punctuation is False
    assert state.change_justification == "original"
    assert state.remove_paragraph_spacing is False
    assert state.kfx_doc_type == "doc"
    assert state.kfx_pages is None
    assert state.docx_page_size == "default"
    assert state.docx_no_toc is False
    assert state.epub_version == "default"
    assert state.epub_inline_toc is False
    assert state.epub_remove_background is False
    assert state.epub_split_volumes is False
    assert state.epub_standardize_footnotes is False
    assert state.pdf_paper_size == "default"
    assert state.pdf_page_numbers is False


def test_set_request_option_rejects_epub_only_flags_for_non_epub() -> None:
    state = ConversionRequestState(
        input_file_path="/tmp/book.pdf",  # noqa: S108
        queued_at=monotonic(),
        input_ext="pdf",
    )
    assert set_request_option(state, "fix_epub", "1") is False
    assert set_request_option(state, "flat_toc", "1") is False
    assert set_request_option(state, "epub_split_volumes", "1") is False
    assert set_request_option(state, "epub_standardize_footnotes", "1") is False


def test_cleanup_expired_requests_removes_stale_state_and_file(tmp_path: Path) -> None:
    stale_file = tmp_path / "stale.epub"
    fresh_file = tmp_path / "fresh.epub"
    stale_file.write_text("stale")
    fresh_file.write_text("fresh")
    queue = {
        "stale": ConversionRequestState(
            input_file_path=str(stale_file),
            queued_at=monotonic() - 100,
            input_ext="epub",
        ),
        "fresh": ConversionRequestState(
            input_file_path=str(fresh_file),
            queued_at=monotonic(),
            input_ext="epub",
        ),
    }

    cleanup_expired_requests(queue, ttl_seconds=60)

    assert "stale" not in queue
    assert stale_file.exists() is False
    assert "fresh" in queue
    assert fresh_file.exists() is True
