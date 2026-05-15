from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from telethon import Button
from telethon.tl.types import KeyboardButtonCallback

HIGHLIGHTED_FORMATS: set[str] = {"azw3", "docx", "epub", "kfx", "md", "mobi", "pdf"}
CONTEXT_TYPES: tuple[str, ...] = ("docx", "epub", "pdf", "kfx")
PANDOC_SHARED_INPUT_TYPES: set[str] = {"doc", "docx", "epub", "html", "md", "odt", "rtf", "txt"}
PANDOC_ONLY_INPUT_TYPES: set[str] = {
    "adoc",
    "asciidoc",
    "mediawiki",
    "org",
    "rst",
    "t2t",
    "tex",
    "textile",
    "tsv",
    "typ",
    "typst",
}
SHARED_BACKEND_OUTPUT_TYPES: set[str] = {"docx", "epub", "txt"}
PANDOC_ONLY_OUTPUT_TYPES: set[str] = {"adoc", "html", "md", "org", "rst", "tex", "typ", "typst"}
PANDOC_TOC_OUTPUT_TYPES: set[str] = {"docx", "epub", "html", "md", "rst", "tex", "typ", "typst"}
PANDOC_NUMBER_SECTION_OUTPUT_TYPES: set[str] = {"docx", "epub", "html", "tex"}
CALIBRE_COMMON_OUTPUT_TYPES: set[str] = {
    "azw3",
    "docx",
    "epub",
    "fb2",
    "htmlz",
    "kepub",
    "lit",
    "lrf",
    "mobi",
    "oeb",
    "pdb",
    "pmlz",
    "rb",
    "rtf",
    "snb",
    "tcr",
    "txt",
    "txtz",
    "zip",
}
POLISH_OUTPUT_TYPES: set[str] = {"azw3", "epub", "kepub"}
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
    (
        "line_height",
        "line_height_label",
        (
            ("default", "default_label"),
            ("125", "125%"),
            ("150", "150%"),
            ("175", "175%"),
            ("200", "200%"),
        ),
    ),
)
BACKEND_VALUE_OPTION: tuple[str, str, tuple[tuple[str, str], ...]] = (
    "conversion_backend",
    "conversion_backend_label",
    (("calibre", "calibre_label"), ("pandoc", "pandoc_label")),
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
        (
            "pdf_font_profile",
            "pdf_font_profile_label",
            (
                ("default", "default_label"),
                ("noto_naskh_arabic", "noto_naskh_arabic_label"),
                ("amiri", "amiri_label"),
                ("ibm_plex_sans_arabic", "ibm_plex_sans_arabic_label"),
            ),
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
        ("epub_split_volumes", "epub_split_volumes_label"),
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
    "epub_split_volumes": "epub_split_volumes",
    "epub_standardize_footnotes": "epub_standardize_footnotes",
    "pdf_page_numbers": "pdf_page_numbers",
    "pandoc_toc": "pandoc_toc",
    "pandoc_number_sections": "pandoc_number_sections",
}
EPUB_ONLY_BOOL_OPTIONS: set[str] = {
    "fix_epub",
    "flat_toc",
    "epub_standardize_footnotes",
    "epub_split_volumes",
}
VALUE_OPTION_ATTRS: dict[str, str] = {
    "change_justification": "change_justification",
    "line_height": "line_height",
    "kfx_doc_type": "kfx_doc_type",
    "kfx_pages": "kfx_pages",
    "docx_page_size": "docx_page_size",
    "epub_version": "epub_version",
    "pdf_paper_size": "pdf_paper_size",
    "pdf_font_profile": "pdf_font_profile",
    "conversion_backend": "conversion_backend",
}
VALUE_OPTION_MAP: dict[str, dict[str, str | int | None]] = {
    "change_justification": {"original": "original", "left": "left", "justify": "justify"},
    "line_height": {"default": None, "125": 125, "150": 150, "175": 175, "200": 200},
    "kfx_doc_type": {"doc": "doc", "book": "book"},
    "kfx_pages": {"none": None, "auto": 0},
    "docx_page_size": {"default": "default", "letter": "letter", "a4": "a4"},
    "epub_version": {"default": "default", "2": "2", "3": "3"},
    "pdf_paper_size": {"default": "default", "letter": "letter", "a4": "a4"},
    "pdf_font_profile": {
        "default": "default",
        "noto_naskh_arabic": "noto_naskh_arabic",
        "amiri": "amiri",
        "ibm_plex_sans_arabic": "ibm_plex_sans_arabic",
    },
    "conversion_backend": {"calibre": "calibre", "pandoc": "pandoc"},
}
EPUB_EXTRA_BOOL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fix_epub", "fix_epub_label"),
    ("flat_toc", "flat_toc_label"),
    ("epub_standardize_footnotes", "epub_standardize_footnotes_label"),
)
PERSISTED_OPTION_ATTRS: tuple[str, ...] = (
    "force_rtl",
    "compress_cover",
    "fix_epub",
    "flat_toc",
    "smarten_punctuation",
    "change_justification",
    "line_height",
    "remove_paragraph_spacing",
    "kfx_doc_type",
    "kfx_pages",
    "options_context",
    "docx_page_size",
    "docx_no_toc",
    "epub_version",
    "epub_inline_toc",
    "epub_remove_background",
    "epub_split_volumes",
    "epub_standardize_footnotes",
    "pdf_paper_size",
    "pdf_font_profile",
    "pdf_page_numbers",
    "conversion_backend",
    "pandoc_toc",
    "pandoc_number_sections",
)
PERSISTED_OPTION_ATTRS_SET = set(PERSISTED_OPTION_ATTRS)
PERSISTED_BOOL_ATTRS = set(BOOL_OPTION_ATTRS.values())
PERSISTED_EPUB_ONLY_BOOL_ATTRS = {BOOL_OPTION_ATTRS[key] for key in EPUB_ONLY_BOOL_OPTIONS}
PERSISTED_VALUE_ALLOWED_BY_ATTR = {
    VALUE_OPTION_ATTRS[key]: set(value_map.values()) for key, value_map in VALUE_OPTION_MAP.items()
}


@dataclass
class ConversionRequestState:
    input_file_path: str
    queued_at: float
    input_ext: str
    selected_output_type: str | None = None
    force_rtl: bool = False
    compress_cover: bool = False
    fix_epub: bool = False
    flat_toc: bool = False
    smarten_punctuation: bool = False
    change_justification: str = "original"
    line_height: int | None = None
    remove_paragraph_spacing: bool = False
    kfx_doc_type: str = "doc"
    kfx_pages: int | None = None
    options_context: str = "docx"
    docx_page_size: str = "default"
    docx_no_toc: bool = False
    epub_version: str = "default"
    epub_inline_toc: bool = False
    epub_remove_background: bool = False
    epub_split_volumes: bool = False
    epub_standardize_footnotes: bool = False
    pdf_paper_size: str = "default"
    pdf_font_profile: str = "default"
    pdf_page_numbers: bool = False
    conversion_backend: str = "calibre"
    pandoc_toc: bool = False
    pandoc_number_sections: bool = False


@dataclass
class OptionsKeyboardContext:
    rows: list[list[KeyboardButtonCallback]]
    request_id: str
    state: ConversionRequestState
    labels: dict[str, str]


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


def _append_bool_row(
    context: OptionsKeyboardContext,
    option_key: str,
    label_key: str,
) -> None:
    selected = getattr(context.state, BOOL_OPTION_ATTRS[option_key], False)
    context.rows.append(
        [
            Button.inline(
                f"{context.labels[label_key]}{' ✅' if selected else ''}",
                data=f"opt|{option_key}|{0 if selected else 1}|{context.request_id}",
            )
        ]
    )


def _append_value_row(
    context: OptionsKeyboardContext,
    option_key: str,
    prefix_label_key: str,
    value_specs: tuple[tuple[str, str], ...],
) -> None:
    option_attr = VALUE_OPTION_ATTRS[option_key]
    selected_value = getattr(context.state, option_attr)
    row_buttons: list[KeyboardButtonCallback] = []
    for index, (value_token, label_key) in enumerate(value_specs):
        label = context.labels.get(label_key, label_key)
        prefix = f"{context.labels[prefix_label_key]}: " if index == 0 else ""
        target_value = VALUE_OPTION_MAP[option_key][value_token]
        row_buttons.append(
            Button.inline(
                f"{prefix}{label}{' ✅' if selected_value == target_value else ''}",
                data=f"opt|{option_key}|{value_token}|{context.request_id}",
            )
        )
    context.rows.append(row_buttons)


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
    keyboard_context = OptionsKeyboardContext(rows, request_id, state, labels)

    for option_key, label_key in GLOBAL_BOOL_OPTIONS:
        _append_bool_row(keyboard_context, option_key, label_key)
    for option_key, prefix_label_key, value_specs in GLOBAL_VALUE_OPTIONS:
        _append_value_row(keyboard_context, option_key, prefix_label_key, value_specs)
    if state.input_ext in PANDOC_SHARED_INPUT_TYPES:
        _append_value_row(keyboard_context, *BACKEND_VALUE_OPTION)

    for option_key, prefix_label_key, value_specs in CONTEXT_VALUE_OPTIONS[state.options_context]:
        _append_value_row(keyboard_context, option_key, prefix_label_key, value_specs)
    for option_key, label_key in CONTEXT_BOOL_OPTIONS[state.options_context]:
        if option_key in EPUB_ONLY_BOOL_OPTIONS and state.input_ext != "epub":
            continue
        _append_bool_row(keyboard_context, option_key, label_key)

    if state.input_ext == "epub":
        for option_key, label_key in EPUB_EXTRA_BOOL_OPTIONS:
            _append_bool_row(keyboard_context, option_key, label_key)

    rows.append([Button.inline(labels["reset_options_label"], data=f"opt|reset|1|{request_id}")])
    rows.append(
        [
            Button.inline(labels["back_to_formats_label"], data=f"view|formats|{request_id}"),
            Button.inline(labels["cancel_label"], data=f"cancel|{request_id}"),
        ]
    )
    return rows


def route_uses_pandoc(state: ConversionRequestState, output_type: str) -> bool:
    return (
        output_type in PANDOC_ONLY_OUTPUT_TYPES
        or state.input_ext in PANDOC_ONLY_INPUT_TYPES
        or (
            state.conversion_backend == "pandoc"
            and state.input_ext in PANDOC_SHARED_INPUT_TYPES
            and output_type in SHARED_BACKEND_OUTPUT_TYPES
        )
    )


def route_supports_rtl(state: ConversionRequestState, output_type: str) -> bool:
    if route_uses_pandoc(state, output_type):
        return output_type in {"epub", "html", "md"}
    return output_type in {"epub", "pdf"}


def route_option_values(
    state: ConversionRequestState,
    output_type: str,
) -> dict[str, bool | str | int | None]:
    uses_pandoc = route_uses_pandoc(state, output_type)
    is_epub_input = state.input_ext == "epub"
    values: dict[str, bool | str | int | None] = {
        "force_rtl": state.force_rtl if route_supports_rtl(state, output_type) else False,
        "compress_cover": False,
        "fix_epub": state.fix_epub if is_epub_input else False,
        "flat_toc": state.flat_toc if is_epub_input else False,
        "smarten_punctuation": False,
        "change_justification": "original",
        "line_height": None,
        "remove_paragraph_spacing": False,
        "kfx_doc_type": "doc",
        "kfx_pages": None,
        "docx_page_size": "default",
        "docx_no_toc": False,
        "epub_version": "default",
        "epub_inline_toc": False,
        "epub_remove_background": False,
        "epub_split_volumes": False,
        "epub_standardize_footnotes": state.epub_standardize_footnotes if is_epub_input else False,
        "pdf_paper_size": "default",
        "pdf_font_profile": "default",
        "pdf_page_numbers": False,
        "conversion_backend": "pandoc" if uses_pandoc else "calibre",
        "pandoc_toc": state.pandoc_toc
        if uses_pandoc and output_type in PANDOC_TOC_OUTPUT_TYPES
        else False,
        "pandoc_number_sections": (
            state.pandoc_number_sections
            if uses_pandoc and output_type in PANDOC_NUMBER_SECTION_OUTPUT_TYPES
            else False
        ),
    }
    if uses_pandoc:
        return values

    if output_type in POLISH_OUTPUT_TYPES:
        values["compress_cover"] = state.compress_cover
    if output_type in CALIBRE_COMMON_OUTPUT_TYPES:
        values.update(
            {
                "smarten_punctuation": state.smarten_punctuation,
                "change_justification": state.change_justification,
                "line_height": state.line_height,
                "remove_paragraph_spacing": state.remove_paragraph_spacing,
            }
        )
    if output_type == "docx":
        values.update({"docx_page_size": state.docx_page_size, "docx_no_toc": state.docx_no_toc})
    elif output_type == "epub":
        values.update(
            {
                "epub_version": state.epub_version,
                "epub_inline_toc": state.epub_inline_toc,
                "epub_remove_background": state.epub_remove_background,
                "epub_split_volumes": state.epub_split_volumes if is_epub_input else False,
            }
        )
    elif output_type == "pdf":
        values.update(
            {
                "pdf_paper_size": state.pdf_paper_size,
                "pdf_font_profile": state.pdf_font_profile,
                "pdf_page_numbers": state.pdf_page_numbers,
            }
        )
    elif output_type == "kfx":
        values.update({"kfx_doc_type": state.kfx_doc_type, "kfx_pages": state.kfx_pages})
    return values


def _append_route_global_options(
    context: OptionsKeyboardContext,
    output_type: str,
) -> None:
    uses_pandoc = route_uses_pandoc(context.state, output_type)
    if route_supports_rtl(context.state, output_type):
        _append_bool_row(context, "rtl", "force_rtl_label")
    if uses_pandoc and output_type in PANDOC_TOC_OUTPUT_TYPES:
        _append_bool_row(context, "pandoc_toc", "pandoc_toc_label")
    if uses_pandoc and output_type in PANDOC_NUMBER_SECTION_OUTPUT_TYPES:
        _append_bool_row(context, "pandoc_number_sections", "pandoc_number_sections_label")
    if not uses_pandoc and output_type in POLISH_OUTPUT_TYPES:
        _append_bool_row(context, "compress_cover", "compress_cover_label")
    if not uses_pandoc and output_type in CALIBRE_COMMON_OUTPUT_TYPES:
        for option_key, label_key in (
            ("smarten", "smarten_punctuation_label"),
            ("remove_paragraph_spacing", "remove_paragraph_spacing_label"),
        ):
            _append_bool_row(context, option_key, label_key)
        for option_key, prefix_label_key, value_specs in GLOBAL_VALUE_OPTIONS:
            _append_value_row(context, option_key, prefix_label_key, value_specs)


def _append_route_context_options(
    context: OptionsKeyboardContext,
    output_type: str,
) -> None:
    if route_uses_pandoc(context.state, output_type):
        return
    if output_type not in CONTEXT_TYPES:
        return
    for option_key, prefix_label_key, value_specs in CONTEXT_VALUE_OPTIONS[output_type]:
        _append_value_row(context, option_key, prefix_label_key, value_specs)
    for option_key, label_key in CONTEXT_BOOL_OPTIONS[output_type]:
        if option_key == "epub_split_volumes":
            continue
        _append_bool_row(context, option_key, label_key)


def _append_route_epub_input_options(
    context: OptionsKeyboardContext,
    output_type: str,
) -> None:
    if context.state.input_ext != "epub":
        return
    for option_key, label_key in EPUB_EXTRA_BOOL_OPTIONS:
        _append_bool_row(context, option_key, label_key)
    if output_type == "epub" and not route_uses_pandoc(context.state, output_type):
        _append_bool_row(context, "epub_split_volumes", "epub_split_volumes_label")


def build_route_options_keyboard(
    request_id: str,
    state: ConversionRequestState,
    output_type: str,
    labels: dict[str, str],
) -> list[list[KeyboardButtonCallback]]:
    rows: list[list[KeyboardButtonCallback]] = []
    keyboard_context = OptionsKeyboardContext(rows, request_id, state, labels)

    if state.input_ext in PANDOC_SHARED_INPUT_TYPES and output_type in SHARED_BACKEND_OUTPUT_TYPES:
        _append_value_row(keyboard_context, *BACKEND_VALUE_OPTION)
    _append_route_global_options(keyboard_context, output_type)
    _append_route_context_options(keyboard_context, output_type)
    _append_route_epub_input_options(keyboard_context, output_type)

    if rows:
        rows.append(
            [Button.inline(labels["reset_options_label"], data=f"opt|reset|1|{request_id}")]
        )
    rows.append([Button.inline(labels["convert_label"], data=f"run|{output_type}|{request_id}")])
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
        state.line_height = None
        state.remove_paragraph_spacing = False
        state.kfx_doc_type = "doc"
        state.kfx_pages = None
        state.docx_page_size = "default"
        state.docx_no_toc = False
        state.epub_version = "default"
        state.epub_inline_toc = False
        state.epub_remove_background = False
        state.epub_split_volumes = False
        state.epub_standardize_footnotes = False
        state.pdf_paper_size = "default"
        state.pdf_font_profile = "default"
        state.pdf_page_numbers = False
        state.conversion_backend = "calibre"
        state.pandoc_toc = False
        state.pandoc_number_sections = False
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


def state_to_persisted_options(
    state: ConversionRequestState,
) -> dict[str, bool | str | int | None]:
    return {option_attr: getattr(state, option_attr) for option_attr in PERSISTED_OPTION_ATTRS}


def apply_persisted_options(
    state: ConversionRequestState,
    persisted: dict[str, Any] | None,
) -> None:
    if not isinstance(persisted, dict):
        return
    for option_attr, value in persisted.items():
        if option_attr not in PERSISTED_OPTION_ATTRS_SET:
            continue
        if option_attr == "options_context":
            if isinstance(value, str) and value in CONTEXT_TYPES:
                state.options_context = value
            continue
        if option_attr in PERSISTED_BOOL_ATTRS:
            if not isinstance(value, bool):
                continue
            if option_attr in PERSISTED_EPUB_ONLY_BOOL_ATTRS and state.input_ext != "epub":
                continue
            setattr(state, option_attr, value)
            continue
        allowed_values = PERSISTED_VALUE_ALLOWED_BY_ATTR.get(option_attr)
        if allowed_values is not None and value in allowed_values:
            setattr(state, option_attr, value)


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
