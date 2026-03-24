# ruff: noqa: RUF001

import re

from lxml import etree

ARABIC_NUMBER_BETWEEN_BRACKETS_PATTERN = re.compile(r"(\(\^?[\u0660-\u0669]+\))")
ARABIC_NUMBER_BETWEEN_SQUARE_BRACKETS_PATTERN = re.compile(r"(\[\^?[\u0660-\u0669]+\])")
WESTERN_NUMBER_BETWEEN_BRACKETS_PATTERN = re.compile(r"(\(\^?[0-9]+\))")
WESTERN_NUMBER_BETWEEN_SQUARE_BRACKETS_PATTERN = re.compile(r"(\[\^?[0-9]+\])")
ARABIC_NUMBER_BETWEEN_CURLY_BRACES_PATTERN = re.compile(r"{.+?(\(\^?[\u0660-\u0669]+\)).+?}")
AYAH_PATTERN = re.compile(r"﴿[\s\S]+?﴾")

HAMESH_LINE_NUMBER_PATTERN = re.compile(r"^\s*(\(\s*\^?[\u0660-\u0669\d]+\s*\))(.*)$")
HAMESH_LINE_NUMBER_SQUARE_PATTERN = re.compile(r"^\s*(\[\s*\^?[\u0660-\u0669\d]+\s*\])(.*)$")
HAMESH_LINE_NUMBER_PLAIN_PATTERN = re.compile(
    r"^\s*([\u0660-\u0669\d]+)(?:\s*[-–—.:،)]\s*|\s+)(.*)$"
)

BR_TAG_PATTERN = re.compile(r"(?i)</?(?:\w+:)?br\s*/?>")
LEADING_CONTINUATION_PATTERN = re.compile(
    r'(?s)(<div class="hamesh">)\s*<aside id="fn0" epub:type="footnote"><span>(.*?)</span></aside>'
)
LAST_FOOTNOTE_SPAN_PATTERN = re.compile(
    r'(?s)(<aside id="fn\d+" epub:type="footnote">.*?<span>)(.*?)(</span></aside>)'
    r'(?![\s\S]*<aside id="fn\d+" epub:type="footnote">)'
)

EPUB_NS = "http://www.idpf.org/2007/ops"

etree.register_namespace("epub", EPUB_NS)


def _match_hamesh_line_number(line: str) -> re.Match[str] | None:
    for pattern in (
        HAMESH_LINE_NUMBER_PATTERN,
        HAMESH_LINE_NUMBER_SQUARE_PATTERN,
        HAMESH_LINE_NUMBER_PLAIN_PATTERN,
    ):
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

        idx = 0
        if lines[0].startswith("="):
            continuation_lines = [lines[0]]
            idx = 1
            while idx < len(lines) and not _match_hamesh_line_number(lines[idx]):
                continuation_lines.append(lines[idx])
                idx += 1
            continuation_text = "<br />".join(continuation_lines).strip()
            if continuation_text:
                items[0] = (
                    f'<aside id="fn0" epub:type="footnote"><span>{continuation_text}</span></aside>'
                )

        while idx < len(lines):
            match = _match_hamesh_line_number(lines[idx])
            if not match:
                idx += 1
                continue
            counter += 1
            number = match.group(1)
            content_lines = [match.group(2).strip()] if match.group(2).strip() else []
            idx += 1
            while idx < len(lines) and not _match_hamesh_line_number(lines[idx]):
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


def update_hamesh_html(html_fragment: str) -> str:  # noqa: C901,PLR0915
    def tag_name(elem: etree._Element) -> str:
        return elem.tag.rsplit("}", 1)[-1].lower() if isinstance(elem.tag, str) else ""

    def has_hamesh_class(elem: etree._Element) -> bool:
        return "hamesh" in str(elem.attrib.get("class") or "").split()

    def parse_fragment_element(fragment: str) -> etree._Element | None:
        try:
            wrapper = etree.fromstring(f'<root xmlns:epub="{EPUB_NS}">{fragment}</root>')
        except etree.ParseError:
            return None
        return next(iter(wrapper), None)

    def collect_hamesh_nodes(
        parent: etree._Element, out: list[tuple[etree._Element, etree._Element]]
    ) -> None:
        for child in list(parent):
            if tag_name(child) == "p" and has_hamesh_class(child):
                out.append((parent, child))
            collect_hamesh_nodes(child, out)

    try:
        root = etree.fromstring(f'<root xmlns:epub="{EPUB_NS}">{html_fragment}</root>')
    except etree.ParseError:
        return html_fragment

    hamesh_nodes: list[tuple[etree._Element, etree._Element]] = []
    collect_hamesh_nodes(root, hamesh_nodes)
    if not hamesh_nodes:
        return html_fragment

    hamesh_items = get_hamesh_items(
        [etree.tostring(node, encoding="unicode", method="xml") for _parent, node in hamesh_nodes]
    )
    new_hamesh_asides: list[etree._Element] = []

    continuation = hamesh_items.pop(0, None)
    if continuation:
        continuation_elem = parse_fragment_element(continuation)
        if continuation_elem is not None:
            new_hamesh_asides.append(continuation_elem)

    footnote_count = 1
    linked_notes = 0

    def rewrite_paragraph(parent: etree._Element) -> None:  # noqa: C901
        nonlocal footnote_count, linked_notes
        i = 0
        while i < len(parent):
            child = parent[i]
            if tag_name(child) == "p" and not has_hamesh_class(child):
                paragraph_html = etree.tostring(child, encoding="unicode", method="xml")
                temp = paragraph_html

                placeholders: list[tuple[str, str]] = []
                for idx, ayah in enumerate(AYAH_PATTERN.findall(temp), start=1):
                    key = f"PLACEHOLDER_{idx}"
                    placeholders.append((key, ayah))
                    temp = temp.replace(ayah, key)

                replacements: list[tuple[int, int, str]] = []
                ayah_match = ARABIC_NUMBER_BETWEEN_CURLY_BRACES_PATTERN.search(temp)
                ref_matches = sorted(
                    [
                        *ARABIC_NUMBER_BETWEEN_BRACKETS_PATTERN.finditer(temp),
                        *ARABIC_NUMBER_BETWEEN_SQUARE_BRACKETS_PATTERN.finditer(temp),
                        *WESTERN_NUMBER_BETWEEN_BRACKETS_PATTERN.finditer(temp),
                        *WESTERN_NUMBER_BETWEEN_SQUARE_BRACKETS_PATTERN.finditer(temp),
                    ],
                    key=lambda match: match.start(),
                )
                for match in ref_matches:
                    number = match.group(1)
                    if footnote_count not in hamesh_items:
                        continue
                    if (
                        ayah_match
                        and number in ayah_match.group(0)
                        and match.start() > ayah_match.start()
                    ):
                        continue
                    replacements.append(
                        (
                            match.start(),
                            match.end(),
                            f'<a href="#fn{footnote_count}" epub:type="noteref" role="doc-noteref" '
                            f'id="fnref{footnote_count}" class="fn nu">{number}</a>',
                        )
                    )
                    note_elem = parse_fragment_element(hamesh_items[footnote_count])
                    if note_elem is not None:
                        new_hamesh_asides.append(note_elem)
                    footnote_count += 1
                    linked_notes += 1

                if replacements:
                    for start, end, replacement in reversed(replacements):
                        temp = temp[:start] + replacement + temp[end:]
                    for key, ayah in placeholders:
                        temp = temp.replace(key, ayah)
                    new_elem = parse_fragment_element(temp)
                    if new_elem is not None:
                        new_elem.tail = child.tail
                        parent.remove(child)
                        parent.insert(i, new_elem)
                        child = new_elem

            rewrite_paragraph(child)
            i += 1

    rewrite_paragraph(root)

    if linked_notes == 0 and not continuation:
        return html_fragment

    new_hamesh = etree.Element("div", {"class": "hamesh"})
    for aside in new_hamesh_asides:
        new_hamesh.append(aside)
    if not len(new_hamesh):
        return html_fragment

    first_parent, first_node = hamesh_nodes[0]
    try:
        first_index = list(first_parent).index(first_node)
    except ValueError:
        return html_fragment
    first_parent.remove(first_node)
    first_parent.insert(first_index, new_hamesh)

    for parent, node in hamesh_nodes[1:]:
        if node in list(parent):
            parent.remove(node)

    parts: list[str] = [root.text or ""]
    for child in list(root):
        parts.append(etree.tostring(child, encoding="unicode", method="xml"))
        parts.append(child.tail or "")
    return "".join(parts)


def pop_leading_continuation(html_fragment: str) -> tuple[str, str | None]:
    match = LEADING_CONTINUATION_PATTERN.search(html_fragment)
    if not match:
        return html_fragment, None

    continuation = match.group(2).strip()
    if continuation.startswith("="):
        continuation = continuation[1:].strip()

    stripped = html_fragment[: match.start()] + match.group(1) + html_fragment[match.end() :]
    stripped = stripped.replace('<div class="hamesh"></div>', "")
    return stripped, continuation or None


def append_to_last_footnote(html_fragment: str, continuation: str) -> tuple[str, bool]:
    match = LAST_FOOTNOTE_SPAN_PATTERN.search(html_fragment)
    if not match:
        return html_fragment, False

    current = match.group(2).rstrip()
    joiner = "<br />" if current else ""
    merged = f"{match.group(1)}{current}{joiner}{continuation}{match.group(3)}"
    return html_fragment[: match.start()] + merged + html_fragment[match.end() :], True
