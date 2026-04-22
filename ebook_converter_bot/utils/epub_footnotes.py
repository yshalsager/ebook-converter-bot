# ruff: noqa: RUF001

import re
from dataclasses import dataclass, field

from lxml import etree

REFERENCE_MARKER_PATTERN = re.compile(r"(\(\^?[\u0660-\u0669\d]+\)|\[\^?[\u0660-\u0669\d]+\])")
MARKER_DIGITS_PATTERN = re.compile(r"[\u0660-\u0669\d]+")
ARABIC_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

HAMESH_LINE_NUMBER_PATTERN = re.compile(r"^\s*(\(\s*\^?[\u0660-\u0669\d]+\s*\))(.*)$")
HAMESH_LINE_NUMBER_SQUARE_PATTERN = re.compile(r"^\s*(\[\s*\^?[\u0660-\u0669\d]+\s*\])(.*)$")
HAMESH_LINE_NUMBER_PLAIN_PATTERN = re.compile(
    r"^\s*([\u0660-\u0669\d]+)(?:\s*[-–—.:،)]\s*|\s+)(.*)$"
)
EXPLICIT_HAMESH_LINE_PATTERNS = (HAMESH_LINE_NUMBER_PATTERN, HAMESH_LINE_NUMBER_SQUARE_PATTERN)

BR_TAG_PATTERN = re.compile(r"(?i)</?(?:\w+:)?br\s*/?>")
LAST_FOOTNOTE_SPAN_PATTERN = re.compile(
    r'(?s)(<aside id="fn\d+" epub:type="footnote">.*?<span>)(.*?)(</span></aside>)'
    r'(?![\s\S]*<aside id="fn\d+" epub:type="footnote">)'
)

EPUB_NS = "http://www.idpf.org/2007/ops"

etree.register_namespace("epub", EPUB_NS)


def _tag_name(elem: etree._Element) -> str:
    return elem.tag.rsplit("}", 1)[-1].lower() if isinstance(elem.tag, str) else ""


def _inner_html(elem: etree._Element) -> str:
    parts: list[str] = [elem.text or ""]
    for child in list(elem):
        parts.append(etree.tostring(child, encoding="unicode", method="xml", with_tail=False))
        parts.append(child.tail or "")
    return "".join(parts)


def _is_empty_node(elem: etree._Element) -> bool:
    return not (elem.text or "").strip() and len(list(elem)) == 0


def _has_hamesh_class(elem: etree._Element) -> bool:
    return "hamesh" in str(elem.attrib.get("class") or "").split()


def _parse_fragment_root(html_fragment: str) -> etree._Element | None:
    try:
        return etree.fromstring(f'<root xmlns:epub="{EPUB_NS}">{html_fragment}</root>')
    except etree.ParseError:
        return None


def _parse_fragment_element(fragment: str) -> etree._Element | None:
    wrapper = _parse_fragment_root(fragment)
    if wrapper is None:
        return None
    return next(iter(wrapper), None)


def _is_fn0_footnote_aside(elem: etree._Element) -> bool:
    if _tag_name(elem) != "aside":
        return False
    if str(elem.attrib.get("id") or "").strip() != "fn0":
        return False
    footnote_type = (
        str(elem.attrib.get(f"{{{EPUB_NS}}}type") or "").strip()
        or str(elem.attrib.get("epub:type") or "").strip()
    )
    return footnote_type == "footnote"


def _find_fn0_footnote_aside(root: etree._Element) -> etree._Element | None:
    return next((elem for elem in root.iter() if _is_fn0_footnote_aside(elem)), None)


def _extract_continuation_from_fn0(fn0_aside: etree._Element) -> str | None:
    span = next((child for child in list(fn0_aside) if _tag_name(child) == "span"), None)
    if span is None:
        return None
    span_content = _inner_html(span).strip()
    left_trimmed = span_content.lstrip()
    if not left_trimmed.startswith("="):
        return None
    return left_trimmed[1:].strip() or None


def _prune_empty_ancestors(node: etree._Element, root: etree._Element) -> None:
    parent = node
    while parent is not root and _is_empty_node(parent):
        grand_parent = parent.getparent()
        if grand_parent is None:
            break
        grand_parent.remove(parent)
        parent = grand_parent


def _collect_hamesh_nodes(
    parent: etree._Element, out: list[tuple[etree._Element, etree._Element]]
) -> None:
    for child in list(parent):
        if _tag_name(child) == "p" and _has_hamesh_class(child):
            out.append((parent, child))
        _collect_hamesh_nodes(child, out)


def _neighbor_non_space_char(text: str, index: int, *, forward: bool) -> str | None:
    step = 1 if forward else -1
    i = index
    while 0 <= i < len(text):
        char = text[i]
        if not char.isspace():
            return char
        i += step
    return None


def _is_ayah_context_reference(text: str, match: re.Match[str]) -> bool:
    if text[: match.start()].count("﴿") > text[: match.start()].count("﴾"):
        return True
    prev_char = _neighbor_non_space_char(text, match.start() - 1, forward=False)
    next_char = _neighbor_non_space_char(text, match.end(), forward=True)
    return prev_char == "﴿" or next_char == "﴾"


def _normalize_digits(text: str) -> str:
    return text.translate(ARABIC_DIGIT_TRANSLATION)


def _marker_meta(marker: str) -> tuple[str, bool, str]:
    stripped = marker.strip()
    number_match = MARKER_DIGITS_PATTERN.search(stripped)
    number = _normalize_digits(number_match.group(0)) if number_match else ""
    has_caret = "^" in stripped
    bracket = (
        "square" if stripped.startswith("[") else "paren" if stripped.startswith("(") else "plain"
    )
    return number, has_caret, bracket


@dataclass(frozen=True)
class _NoteMeta:
    note_id: int
    number: str
    has_caret: bool
    bracket: str


@dataclass(frozen=True)
class _ReferenceCandidate:
    start: int
    end: int
    marker: str
    number: str
    has_caret: bool
    bracket: str
    in_ayah: bool


@dataclass
class _ParagraphContext:
    paragraph: etree._Element
    html: str
    candidates: list[_ReferenceCandidate]
    replacements: list[tuple[int, int, str]] = field(default_factory=list)


_FlatCandidate = tuple[int, _ReferenceCandidate]


def _collect_body_paragraphs(parent: etree._Element, out: list[etree._Element]) -> None:
    for child in list(parent):
        if _tag_name(child) == "p" and not _has_hamesh_class(child):
            out.append(child)
        _collect_body_paragraphs(child, out)


def _collect_reference_candidates(paragraph_html: str) -> list[_ReferenceCandidate]:
    candidates: list[_ReferenceCandidate] = []
    for match in REFERENCE_MARKER_PATTERN.finditer(paragraph_html):
        marker = match.group(1)
        number, has_caret, bracket = _marker_meta(marker)
        if not number:
            continue
        candidates.append(
            _ReferenceCandidate(
                start=match.start(),
                end=match.end(),
                marker=marker,
                number=number,
                has_caret=has_caret,
                bracket=bracket,
                in_ayah=_is_ayah_context_reference(paragraph_html, match),
            )
        )
    return candidates


def _note_meta_from_aside_html(note_id: int, aside_html: str) -> _NoteMeta | None:
    aside_elem = _parse_fragment_element(aside_html)
    if aside_elem is None or _tag_name(aside_elem) != "aside":
        return None
    anchor = next((child for child in list(aside_elem) if _tag_name(child) == "a"), None)
    if anchor is None:
        return None
    marker = "".join(anchor.itertext()).strip()
    number, has_caret, bracket = _marker_meta(marker)
    if not number:
        return None
    return _NoteMeta(note_id=note_id, number=number, has_caret=has_caret, bracket=bracket)


def _pick_candidate_index(
    note: _NoteMeta,
    flat_candidates: list[_FlatCandidate],
    used_flat_indexes: set[int],
    start_index: int,
) -> int | None:
    matching = [
        idx
        for idx in range(start_index, len(flat_candidates))
        if idx not in used_flat_indexes and flat_candidates[idx][1].number == note.number
    ]
    if not matching:
        return None

    style_matching = [
        idx for idx in matching if flat_candidates[idx][1].has_caret == note.has_caret
    ]
    pool = style_matching or matching

    bracket_matching = [idx for idx in pool if flat_candidates[idx][1].bracket == note.bracket]
    pool = bracket_matching or pool

    safe_pool = [
        idx
        for idx in pool
        if (not flat_candidates[idx][1].in_ayah) or flat_candidates[idx][1].has_caret
    ]
    pool = safe_pool or pool

    return pool[0]


def _replace_paragraph_in_tree(old: etree._Element, new_fragment: str) -> bool:
    new_elem = _parse_fragment_element(new_fragment)
    if new_elem is None:
        return False
    parent = old.getparent()
    if parent is None:
        return False
    try:
        index = list(parent).index(old)
    except ValueError:
        return False
    new_elem.tail = old.tail
    parent.remove(old)
    parent.insert(index, new_elem)
    return True


def _build_paragraph_contexts(root: etree._Element) -> list[_ParagraphContext]:
    paragraphs: list[etree._Element] = []
    _collect_body_paragraphs(root, paragraphs)
    contexts: list[_ParagraphContext] = []
    for paragraph in paragraphs:
        paragraph_html = etree.tostring(paragraph, encoding="unicode", method="xml")
        contexts.append(
            _ParagraphContext(
                paragraph=paragraph,
                html=paragraph_html,
                candidates=_collect_reference_candidates(paragraph_html),
            )
        )
    return contexts


def _collect_note_meta(hamesh_items: dict[int, str]) -> list[_NoteMeta]:
    return [
        meta
        for note_id in sorted(key for key in hamesh_items if key > 0)
        if (meta := _note_meta_from_aside_html(note_id, hamesh_items[note_id])) is not None
    ]


def _assign_note_replacements(
    note_meta: list[_NoteMeta],
    flat_candidates: list[_FlatCandidate],
    contexts: list[_ParagraphContext],
    hamesh_items: dict[int, str],
    new_hamesh_asides: list[etree._Element],
) -> int:
    linked_notes = 0
    used_flat_indexes: set[int] = set()
    cursor = 0

    for note in note_meta:
        picked = _pick_candidate_index(note, flat_candidates, used_flat_indexes, cursor)
        if picked is None:
            continue
        used_flat_indexes.add(picked)
        cursor = picked + 1

        context_idx, candidate = flat_candidates[picked]
        contexts[context_idx].replacements.append(
            (
                candidate.start,
                candidate.end,
                f'<a href="#fn{note.note_id}" epub:type="noteref" role="doc-noteref" '
                f'id="fnref{note.note_id}" class="fn nu">{candidate.marker}</a>',
            )
        )

        note_elem = _parse_fragment_element(hamesh_items[note.note_id])
        if note_elem is not None:
            new_hamesh_asides.append(note_elem)
        hamesh_items.pop(note.note_id, None)
        linked_notes += 1

    return linked_notes


def _rewrite_body_footnote_links(
    root: etree._Element,
    hamesh_items: dict[int, str],
    new_hamesh_asides: list[etree._Element],
) -> int:
    contexts = _build_paragraph_contexts(root)
    if not contexts:
        return 0

    note_meta = _collect_note_meta(hamesh_items)
    flat_candidates = [
        (context_idx, candidate)
        for context_idx, context in enumerate(contexts)
        for candidate in context.candidates
    ]
    linked_notes = _assign_note_replacements(
        note_meta,
        flat_candidates,
        contexts,
        hamesh_items,
        new_hamesh_asides,
    )
    for context in contexts:
        if not context.replacements:
            continue
        updated = context.html
        for start, end, replacement in sorted(
            context.replacements, key=lambda item: item[0], reverse=True
        ):
            updated = updated[:start] + replacement + updated[end:]
        _replace_paragraph_in_tree(context.paragraph, updated)
    return linked_notes


def _replace_hamesh_nodes(
    hamesh_nodes: list[tuple[etree._Element, etree._Element]],
    new_hamesh_asides: list[etree._Element],
) -> bool:
    new_hamesh = etree.Element("div", {"class": "hamesh"})
    for aside in new_hamesh_asides:
        new_hamesh.append(aside)
    if not len(new_hamesh):
        return False

    first_parent, first_node = hamesh_nodes[0]
    try:
        first_index = list(first_parent).index(first_node)
    except ValueError:
        return False
    first_parent.remove(first_node)
    first_parent.insert(first_index, new_hamesh)

    for parent, node in hamesh_nodes[1:]:
        if node in list(parent):
            parent.remove(node)
    return True


def _footnote_aside_html_to_line(aside_html: str) -> str | None:
    aside_elem = _parse_fragment_element(aside_html)
    if aside_elem is None or _tag_name(aside_elem) != "aside":
        return None
    anchor = next((child for child in list(aside_elem) if _tag_name(child) == "a"), None)
    span = next((child for child in list(aside_elem) if _tag_name(child) == "span"), None)
    number = "".join(anchor.itertext()).strip() if anchor is not None else ""
    content = _inner_html(span).strip() if span is not None else ""
    if number and content:
        if number.startswith(("(", "[")) and number.endswith((")", "]")):
            return f"{number} {content}"
        return f"{number} - {content}"
    return content or number or None


def _append_lines_to_continuation_aside(continuation_aside_html: str, lines: list[str]) -> str:
    if not lines:
        return continuation_aside_html
    continuation_elem = _parse_fragment_element(continuation_aside_html)
    if continuation_elem is None or _tag_name(continuation_elem) != "aside":
        return continuation_aside_html

    span = next((child for child in list(continuation_elem) if _tag_name(child) == "span"), None)
    if span is None:
        return continuation_aside_html

    current = _inner_html(span).strip()
    extra = "<br />".join(lines)
    merged = f"{current}<br />{extra}" if current and extra else current or extra
    replacement = _parse_fragment_element(f"<span>{merged}</span>")
    if replacement is None:
        return continuation_aside_html

    replacement.tail = span.tail
    span_index = list(continuation_elem).index(span)
    continuation_elem.remove(span)
    continuation_elem.insert(span_index, replacement)
    return etree.tostring(continuation_elem, encoding="unicode", method="xml")


def _append_lines_to_aside_element(aside_elem: etree._Element, lines: list[str]) -> None:
    if not lines:
        return
    span = next((child for child in list(aside_elem) if _tag_name(child) == "span"), None)
    if span is None:
        return
    current = _inner_html(span).strip()
    extra = "<br />".join(lines)
    merged = f"{current}<br />{extra}" if current and extra else current or extra
    replacement = _parse_fragment_element(f"<span>{merged}</span>")
    if replacement is None:
        return
    replacement.tail = span.tail
    span_index = list(aside_elem).index(span)
    aside_elem.remove(span)
    aside_elem.insert(span_index, replacement)


def _match_hamesh_line_number(line: str, *, allow_plain: bool) -> re.Match[str] | None:
    patterns = (
        (
            *EXPLICIT_HAMESH_LINE_PATTERNS,
            HAMESH_LINE_NUMBER_PLAIN_PATTERN,
        )
        if allow_plain
        else EXPLICIT_HAMESH_LINE_PATTERNS
    )
    for pattern in patterns:
        match = pattern.match(line)
        if match:
            return match
    return None


def get_hamesh_items(hamesh_html: list[str]) -> dict[int, str]:
    items: dict[int, str] = {}
    counter = 0

    for raw_html in hamesh_html:
        current = re.sub(r"(?is)^<\s*(?:\w+:)?p\b[^>]*>", "", raw_html.strip())
        current = re.sub(r"(?is)</\s*(?:\w+:)?p\s*>\s*$", "", current)
        lines = [line.strip() for line in BR_TAG_PATTERN.split(current) if line.strip()]
        if not lines:
            continue
        allow_plain = not any(
            pattern.match(line) for pattern in EXPLICIT_HAMESH_LINE_PATTERNS for line in lines
        )

        idx = 0
        if lines[0].startswith("="):
            continuation_lines = [lines[0]]
            idx += 1
            while idx < len(lines) and not _match_hamesh_line_number(
                lines[idx], allow_plain=allow_plain
            ):
                continuation_lines.append(lines[idx])
                idx += 1
            continuation_text = "<br />".join(continuation_lines).strip()
            if continuation_text:
                items[0] = (
                    f'<aside id="fn0" epub:type="footnote"><span>{continuation_text}</span></aside>'
                )

        while idx < len(lines):
            match = _match_hamesh_line_number(lines[idx], allow_plain=allow_plain)
            if not match:
                idx += 1
                continue
            counter += 1
            number = match.group(1)
            content_lines = [match.group(2).strip()] if match.group(2).strip() else []
            idx += 1
            while idx < len(lines) and not _match_hamesh_line_number(
                lines[idx], allow_plain=allow_plain
            ):
                content_lines.append(lines[idx])
                idx += 1
            content = "<br />".join(line.strip() for line in content_lines if line.strip())
            content_html = f" {content}" if content else ""
            aside = (
                f'<aside id="fn{counter}" epub:type="footnote">'
                f'<a href="#fnref{counter}" class="nu">{number}</a><span>{content_html}</span>'
                "</aside>"
            )
            items[counter] = aside
    return items


def update_hamesh_html(html_fragment: str) -> str:
    root = _parse_fragment_root(html_fragment)
    if root is None:
        return html_fragment

    hamesh_nodes: list[tuple[etree._Element, etree._Element]] = []
    _collect_hamesh_nodes(root, hamesh_nodes)
    if not hamesh_nodes:
        return html_fragment

    hamesh_items = get_hamesh_items(
        [etree.tostring(node, encoding="unicode", method="xml") for _parent, node in hamesh_nodes]
    )
    new_hamesh_asides: list[etree._Element] = []

    continuation = hamesh_items.pop(0, None)

    linked_notes = _rewrite_body_footnote_links(root, hamesh_items, new_hamesh_asides)
    remaining_lines = [
        line
        for _, value in sorted((key, value) for key, value in hamesh_items.items() if key > 0)
        if (line := _footnote_aside_html_to_line(value))
    ]

    if continuation and linked_notes == 0:
        continuation = _append_lines_to_continuation_aside(continuation, remaining_lines)
        remaining_lines = []

    if continuation:
        continuation_elem = _parse_fragment_element(continuation)
        if continuation_elem is not None:
            new_hamesh_asides.insert(0, continuation_elem)

    if linked_notes > 0 and remaining_lines:
        last_linked_aside = next(
            (
                aside
                for aside in reversed(new_hamesh_asides)
                if _tag_name(aside) == "aside" and str(aside.attrib.get("id") or "") != "fn0"
            ),
            None,
        )
        if last_linked_aside is not None:
            _append_lines_to_aside_element(last_linked_aside, remaining_lines)

    if linked_notes == 0 and not continuation:
        return html_fragment

    if not _replace_hamesh_nodes(hamesh_nodes, new_hamesh_asides):
        return html_fragment

    return _inner_html(root)


def pop_leading_continuation(html_fragment: str) -> tuple[str, str | None]:
    root = _parse_fragment_root(html_fragment)
    if root is None:
        return html_fragment, None

    fn0_aside = _find_fn0_footnote_aside(root)
    if fn0_aside is None:
        return html_fragment, None

    continuation = _extract_continuation_from_fn0(fn0_aside)
    if continuation is None:
        return html_fragment, None

    parent = fn0_aside.getparent()
    if parent is None:
        return html_fragment, None
    parent.remove(fn0_aside)
    _prune_empty_ancestors(parent, root)
    return _inner_html(root), continuation


def append_to_last_footnote(html_fragment: str, continuation: str) -> tuple[str, bool]:
    match = LAST_FOOTNOTE_SPAN_PATTERN.search(html_fragment)
    if not match:
        return html_fragment, False

    current = match.group(2).rstrip()
    joiner = "<br />" if current else ""
    merged = f"{match.group(1)}{current}{joiner}{continuation}{match.group(3)}"
    return html_fragment[: match.start()] + merged + html_fragment[match.end() :], True
