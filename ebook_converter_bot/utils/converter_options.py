from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

HIGHLIGHTED_FORMATS: set[str] = {"azw3", "docx", "epub", "kfx", "mobi", "pdf"}
CONTEXT_TYPES: tuple[str, ...] = ("docx", "epub", "pdf", "kfx")
GLOBAL_BOOL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("rtl", "force_rtl_label"),
    ("compress_cover", "compress_cover_label"),
    ("smarten", "smarten_punctuation_label"),
    ("remove_paragraph_spacing", "remove_paragraph_spacing_label"),
)
GLOBAL_VALUE_OPTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "change_justification",
        "change_justification_label",
        (("original", "original_label"), ("left", "left_label"), ("justify", "justify_label")),
    ),
)
CONTEXT_VALUE_OPTIONS: dict[str, tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]] = {
    "docx": (
        (
            "docx_page_size",
            "docx_page_size_label",
            (("default", "default_label"), ("letter", "letter_label"), ("a4", "a4_label")),
        ),
    ),
    "epub": (
        (
            "epub_version",
            "epub_version_label",
            (("default", "default_label"), ("2", "2"), ("3", "3")),
        ),
    ),
    "pdf": (
        (
            "pdf_paper_size",
            "pdf_paper_size_label",
            (("default", "default_label"), ("letter", "letter_label"), ("a4", "a4_label")),
        ),
    ),
    "kfx": (
        (
            "kfx_doc_type",
            "kfx_doc_type_label",
            (("doc", "pdoc_label"), ("book", "ebok_label")),
        ),
        (
            "kfx_pages",
            "kfx_pages_label",
            (("none", "none_label"), ("auto", "auto_label")),
        ),
    ),
}
CONTEXT_BOOL_OPTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "docx": (("docx_no_toc", "docx_no_toc_label"),),
    "epub": (
        ("epub_inline_toc", "epub_inline_toc_label"),
        ("epub_remove_background", "epub_remove_background_label"),
    ),
    "pdf": (("pdf_page_numbers", "pdf_page_numbers_label"),),
    "kfx": (),
}
BOOL_OPTION_ATTRS: dict[str, str] = {
    "rtl": "force_rtl",
    "compress_cover": "compress_cover",
    "fix_epub": "fix_epub",
    "flat_toc": "flat_toc",
    "smarten": "smarten_punctuation",
    "remove_paragraph_spacing": "remove_paragraph_spacing",
    "docx_no_toc": "docx_no_toc",
    "epub_inline_toc": "epub_inline_toc",
    "epub_remove_background": "epub_remove_background",
    "epub_standardize_footnotes": "epub_standardize_footnotes",
    "pdf_page_numbers": "pdf_page_numbers",
}
EPUB_ONLY_BOOL_OPTIONS: set[str] = {"fix_epub", "flat_toc", "epub_standardize_footnotes"}
VALUE_OPTION_ATTRS: dict[str, str] = {
    "change_justification": "change_justification",
    "kfx_doc_type": "kfx_doc_type",
    "kfx_pages": "kfx_pages",
    "docx_page_size": "docx_page_size",
    "epub_version": "epub_version",
    "pdf_paper_size": "pdf_paper_size",
}
VALUE_OPTION_MAP: dict[str, dict[str, str | int | None]] = {
    "change_justification": {"original": "original", "left": "left", "justify": "justify"},
    "kfx_doc_type": {"doc": "doc", "book": "book"},
    "kfx_pages": {"none": None, "auto": 0},
    "docx_page_size": {"default": "default", "letter": "letter", "a4": "a4"},
    "epub_version": {"default": "default", "2": "2", "3": "3"},
    "pdf_paper_size": {"default": "default", "letter": "letter", "a4": "a4"},
}
EPUB_EXTRA_BOOL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fix_epub", "fix_epub_label"),
    ("flat_toc", "flat_toc_label"),
    ("epub_standardize_footnotes", "epub_standardize_footnotes_label"),
)


@dataclass
class ConversionRequestState:
    input_file_path: str
    queued_at: float
    input_ext: str
    force_rtl: bool = False
    compress_cover: bool = False
    fix_epub: bool = False
    flat_toc: bool = False
    smarten_punctuation: bool = False
    change_justification: str = "original"
    remove_paragraph_spacing: bool = False
    kfx_doc_type: str = "doc"
    kfx_pages: int | None = None
    options_context: str = "docx"
    docx_page_size: str = "default"
    docx_no_toc: bool = False
    epub_version: str = "default"
    epub_inline_toc: bool = False
    epub_remove_background: bool = False
    epub_standardize_footnotes: bool = False
    pdf_paper_size: str = "default"
    pdf_page_numbers: bool = False


def format_button_rows(
    request_id: str,
    output_types: list[str],
    *,
    per_row: int = 3,
) -> list[list[KeyboardButtonCallback]]:
    buttons = [
        Button.inline(
            f"🔸 {output_type}" if output_type in HIGHLIGHTED_FORMATS else output_type,
            data=f"fmt|{output_type}|{request_id}",
        )
        for output_type in output_types
    ]
    return [buttons[i : i + per_row] for i in range(0, len(buttons), per_row)]


def build_options_keyboard(
    request_id: str,
    state: ConversionRequestState,
    labels: dict[str, str],
) -> list[list[KeyboardButtonCallback]]:
    rows: list[list[KeyboardButtonCallback]] = [
        [
            Button.inline(
                f"{'▸ ' if context == state.options_context else ''}{context.upper()}",
                data=f"ctx|{context}|{request_id}",
            )
            for context in CONTEXT_TYPES
        ]
    ]

    def add_bool_row(option_key: str, label_key: str) -> None:
        selected = getattr(state, BOOL_OPTION_ATTRS[option_key], False)
        rows.append(
            [
                Button.inline(
                    f"{labels[label_key]}{' ✅' if selected else ''}",
                    data=f"opt|{option_key}|{0 if selected else 1}|{request_id}",
                )
            ]
        )

    def add_value_row(
        option_key: str, prefix_label_key: str, value_specs: tuple[tuple[str, str], ...]
    ) -> None:
        option_attr = VALUE_OPTION_ATTRS[option_key]
        selected_value = getattr(state, option_attr)
        row_buttons: list[KeyboardButtonCallback] = []
        for index, (value_token, label_key) in enumerate(value_specs):
            label = labels.get(label_key, label_key)
            prefix = f"{labels[prefix_label_key]}: " if index == 0 else ""
            target_value = VALUE_OPTION_MAP[option_key][value_token]
            row_buttons.append(
                Button.inline(
                    f"{prefix}{label}{' ✅' if selected_value == target_value else ''}",
                    data=f"opt|{option_key}|{value_token}|{request_id}",
                )
            )
        rows.append(row_buttons)

    for option_key, label_key in GLOBAL_BOOL_OPTIONS:
        add_bool_row(option_key, label_key)
    for option_key, prefix_label_key, value_specs in GLOBAL_VALUE_OPTIONS:
        add_value_row(option_key, prefix_label_key, value_specs)

    for option_key, prefix_label_key, value_specs in CONTEXT_VALUE_OPTIONS[state.options_context]:
        add_value_row(option_key, prefix_label_key, value_specs)
    for option_key, label_key in CONTEXT_BOOL_OPTIONS[state.options_context]:
        add_bool_row(option_key, label_key)

    if state.input_ext == "epub":
        for option_key, label_key in EPUB_EXTRA_BOOL_OPTIONS:
            add_bool_row(option_key, label_key)

    rows.append([Button.inline(labels["reset_options_label"], data=f"opt|reset|1|{request_id}")])
    rows.append(
        [
            Button.inline(labels["back_to_formats_label"], data=f"view|formats|{request_id}"),
            Button.inline(labels["cancel_label"], data=f"cancel|{request_id}"),
        ]
    )
    return rows


def set_request_option(state: ConversionRequestState, option_key: str, option_value: str) -> bool:
    if option_key == "reset":
        state.force_rtl = False
        state.compress_cover = False
        state.fix_epub = False
        state.flat_toc = False
        state.smarten_punctuation = False
        state.change_justification = "original"
        state.remove_paragraph_spacing = False
        state.kfx_doc_type = "doc"
        state.kfx_pages = None
        state.docx_page_size = "default"
        state.docx_no_toc = False
        state.epub_version = "default"
        state.epub_inline_toc = False
        state.epub_remove_background = False
        state.epub_standardize_footnotes = False
        state.pdf_paper_size = "default"
        state.pdf_page_numbers = False
        return True
    bool_value = {"1": True, "0": False}.get(option_value)
    if option_key in BOOL_OPTION_ATTRS:
        if bool_value is None or (
            option_key in EPUB_ONLY_BOOL_OPTIONS and state.input_ext != "epub"
        ):
            return False
        setattr(state, BOOL_OPTION_ATTRS[option_key], bool_value)
        return True
    if option_key in VALUE_OPTION_ATTRS and option_value in VALUE_OPTION_MAP[option_key]:
        setattr(state, VALUE_OPTION_ATTRS[option_key], VALUE_OPTION_MAP[option_key][option_value])
        return True
    return False


def cleanup_expired_requests(
    queue: dict[str, ConversionRequestState],
    *,
    ttl_seconds: int,
) -> None:
    now: float = monotonic()
    for random_id, state in list(queue.items()):
        if now - state.queued_at <= ttl_seconds:
            continue
        queue.pop(random_id, None)
        Path(state.input_file_path).unlink(missing_ok=True)
