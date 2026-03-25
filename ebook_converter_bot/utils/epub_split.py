from __future__ import annotations

import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from lxml import etree

from ebook_converter_bot.utils.epub_common import (
    escape_xml as _escape_xml,
)
from ebook_converter_bot.utils.epub_common import (
    normalize_lang as _normalize_lang,
)
from ebook_converter_bot.utils.epub_common import (
    relative_zip_path as _relative_zip_path,
)
from ebook_converter_bot.utils.epub_common import (
    resolve_relative_zip_path as _resolve_relative_zip_path,
)

PAGE_FILE_NUMBER_PATTERN = re.compile(r"^(?:page_\d+_|page\d+_)(\d+)\.xhtml$", re.IGNORECASE)
XHTML_NS = "http://www.w3.org/1999/xhtml"

DC_NS = "http://purl.org/dc/elements/1.1/"
RTL_LANGUAGE_CODES = {"ar", "dv", "fa", "he", "ku", "ps", "sd", "ug", "ur", "yi"}
SUPPORTED_SPLIT_LANGUAGES = {"ar", "en"}

SPLIT_LABELS = {
    "ar": {
        "fallback_title": "كتاب",
        "page": "صفحة",
        "book_info": "بطاقة الكتاب",
        "toc": "فهرس الموضوعات",
    },
    "en": {
        "fallback_title": "Book",
        "page": "Page",
        "book_info": "Book Info",
        "toc": "Table of Contents",
    },
}

HEADING_TAGS: set[str] = {"h1", "h2", "h3", "h4", "h5", "h6"}
BRANCH_ITEM_SIZE = 2

BASE_CSS = "body{line-height:1.7;margin:1.5rem}"
xml_parser = etree.XMLParser(resolve_entities=False)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _attr_local_name(attr_name: str) -> str:
    if attr_name.startswith("{"):
        return attr_name.rsplit("}", 1)[-1].lower()
    if ":" in attr_name:
        return attr_name.split(":", 1)[-1].lower()
    return attr_name.lower()


def _is_toc_nav(nav_element: etree._Element) -> bool:
    nav_id = str(nav_element.attrib.get("id") or "").strip().lower()
    if nav_id == "toc":
        return True

    role_tokens = str(nav_element.attrib.get("role") or "").lower().split()
    if "doc-toc" in role_tokens:
        return True

    for attr_name, attr_value in nav_element.attrib.items():
        attr_tokens = str(attr_value).lower().split()
        if _attr_local_name(attr_name) == "type" and "toc" in attr_tokens:
            return True
        if _attr_local_name(attr_name) == "role" and "doc-toc" in attr_tokens:
            return True
    return False


def _to_int(value: str | int | None, fallback: int) -> int:
    if value in (None, ""):
        return fallback
    try:
        return int(str(value))
    except ValueError:
        return fallback


def _split_language(value: str) -> str:
    primary = _normalize_lang(value).split("-", 1)[0]
    return primary if primary in SUPPORTED_SPLIT_LANGUAGES else "en"


def _normalize_page_direction(value: str) -> str:
    direction = str(value or "").strip().lower()
    return direction if direction in {"rtl", "ltr"} else ""


def _infer_text_direction(language: str, page_direction: str) -> str:
    if page_direction in {"rtl", "ltr"}:
        return page_direction
    language_code = _normalize_lang(language).split("-", 1)[0]
    return "rtl" if language_code in RTL_LANGUAGE_CODES else "ltr"


def _get_attribute_by_local_name(element: etree._Element, attr_name: str) -> str:
    for key, value in element.attrib.items():
        if _attr_local_name(key) == attr_name:
            return str(value).strip()
    return ""


def _sanitize_filename(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[/:*?"<>|]+', "_", value)).strip()


def _inner_xml(element: etree._Element) -> str:
    cloned = deepcopy(element)

    def strip_xhtml_namespace(node: etree._Element) -> None:
        if isinstance(node.tag, str) and node.tag.startswith(f"{{{XHTML_NS}}}"):
            node.tag = node.tag.rsplit("}", 1)[-1]
        for attr_name in list(node.attrib):
            if not attr_name.startswith(f"{{{XHTML_NS}}}"):
                continue
            value = node.attrib.pop(attr_name)
            node.attrib[attr_name.rsplit("}", 1)[-1]] = value
        for child in list(node):
            strip_xhtml_namespace(child)

    strip_xhtml_namespace(cloned)
    parts: list[str] = [cloned.text or ""]
    for child in list(cloned):
        parts.append(etree.tostring(child, encoding="unicode", method="xml"))
    return "".join(parts).strip()


def _parse_xml(text: str | bytes) -> etree._Element:
    payload = text if isinstance(text, bytes) else text.encode()
    return etree.fromstring(payload, xml_parser)


def _parse_content_opf(  # noqa: C901, PLR0912, PLR0915
    opf_text: str,
    opf_entry_name: str,
) -> dict[str, Any]:
    root = _parse_xml(opf_text)
    metadata_element = next(
        (elem for elem in root.iter() if _local_name(elem.tag) == "metadata"), None
    )
    manifest_element = next(
        (elem for elem in root.iter() if _local_name(elem.tag) == "manifest"), None
    )
    spine_element = next((elem for elem in root.iter() if _local_name(elem.tag) == "spine"), None)
    opf_dir = opf_entry_name.rsplit("/", 1)[0] if "/" in opf_entry_name else ""

    title = ""
    author = ""
    identifier = ""
    language = ""
    nav_item_ids: set[str] = set()
    info_href = ""
    nav_href = ""
    ncx_href = ""
    stylesheet_candidates: list[str] = []
    manifest_items_by_id: dict[str, dict[str, Any]] = {}

    if metadata_element is not None:
        for child in list(metadata_element):
            tag: str = _local_name(child.tag)
            namespace: str = child.tag.split("}", 1)[0][1:] if child.tag.startswith("{") else ""
            text: str = (child.text or "").strip()
            if namespace != DC_NS:
                continue
            if tag == "title" and not title:
                title = text
            elif tag == "creator" and not author:
                author = text
            elif tag == "identifier" and not identifier:
                identifier = text
            elif tag == "language" and not language:
                language = text

    asset_items: list[dict[str, str]] = []
    if manifest_element is not None:
        for child in list(manifest_element):
            if _local_name(child.tag) != "item":
                continue
            item_id = str(child.attrib.get("id") or "").strip()
            item_id_lower = item_id.lower()
            href = str(child.attrib.get("href") or "").strip()
            media_type = str(child.attrib.get("media-type") or "").strip()
            properties = str(child.attrib.get("properties") or "").strip()
            properties_tokens = properties.lower().split()
            href_lower = href.lower()
            if not href or not media_type:
                continue

            is_nav = (
                "nav" in properties_tokens
                or item_id_lower == "nav"
                or href_lower.endswith("/nav.xhtml")
                or href_lower == "nav.xhtml"
            )
            is_info = (
                item_id_lower == "info"
                or href_lower.endswith("/info.xhtml")
                or href_lower == "info.xhtml"
            )
            is_ncx = (
                item_id_lower == "ncx"
                or media_type == "application/x-dtbncx+xml"
                or href_lower.endswith("/toc.ncx")
                or href_lower == "toc.ncx"
            )
            if not nav_href and is_nav:
                nav_href = href
            if not info_href and is_info:
                info_href = href
            if not ncx_href and is_ncx:
                ncx_href = href
            if item_id and is_nav:
                nav_item_ids.add(item_id)

            resolved_href = _resolve_relative_zip_path(opf_dir, href)
            rebased_href = _relative_zip_path("OEBPS", resolved_href)
            rebased_href_lower = rebased_href.lower()
            is_text_page = media_type in {"application/xhtml+xml", "text/html"} and not (
                is_nav or is_info
            )
            if media_type == "text/css":
                if item_id_lower == "css":
                    if resolved_href in stylesheet_candidates:
                        stylesheet_candidates.remove(resolved_href)
                    stylesheet_candidates.insert(0, resolved_href)
                elif resolved_href not in stylesheet_candidates:
                    stylesheet_candidates.append(resolved_href)

            if (
                item_id_lower in {"info", "nav", "ncx", "css"}
                or is_nav
                or is_info
                or rebased_href_lower in {"info.xhtml", "nav.xhtml", "toc.ncx", "styles.css"}
                or (is_text_page and rebased_href_lower.startswith("text/"))
            ):
                if item_id:
                    manifest_items_by_id[item_id] = {
                        "resolved_href": resolved_href,
                        "is_text_page": is_text_page,
                    }
                continue

            asset_items.append(
                {
                    "href": rebased_href,
                    "media_type": media_type,
                    "properties": properties,
                }
            )
            if item_id:
                manifest_items_by_id[item_id] = {
                    "resolved_href": resolved_href,
                    "is_text_page": is_text_page,
                }

    include_toc_page = True
    page_progression_direction = ""
    spine_page_candidates: list[str] = []
    if spine_element is not None:
        page_progression_direction = _normalize_page_direction(
            _get_attribute_by_local_name(spine_element, "page-progression-direction")
        )
        include_toc_page = False
        for item in list(spine_element):
            if _local_name(item.tag) != "itemref":
                continue
            idref = (item.attrib.get("idref") or "").strip()
            if idref and (idref in nav_item_ids or (not nav_item_ids and idref == "nav")):
                include_toc_page = True
            if not idref:
                continue
            spine_item = manifest_items_by_id.get(idref)
            if not spine_item or not bool(spine_item.get("is_text_page")):
                continue
            resolved_href = str(spine_item.get("resolved_href") or "").strip()
            if resolved_href and resolved_href not in spine_page_candidates:
                spine_page_candidates.append(resolved_href)

    info_candidates: list[str] = []
    nav_candidates: list[str] = []
    ncx_candidates: list[str] = []
    if info_href:
        info_candidates.append(_resolve_relative_zip_path(opf_dir, info_href))
    if nav_href:
        nav_candidates.append(_resolve_relative_zip_path(opf_dir, nav_href))
    if ncx_href:
        ncx_candidates.append(_resolve_relative_zip_path(opf_dir, ncx_href))
    info_candidates.extend(
        [f"{opf_dir}/info.xhtml" if opf_dir else "info.xhtml", "OEBPS/info.xhtml"]
    )
    nav_candidates.extend([f"{opf_dir}/nav.xhtml" if opf_dir else "nav.xhtml", "OEBPS/nav.xhtml"])
    ncx_candidates.extend([f"{opf_dir}/toc.ncx" if opf_dir else "toc.ncx", "OEBPS/toc.ncx"])
    for candidate in (
        f"{opf_dir}/styles.css" if opf_dir else "styles.css",
        "OEBPS/styles.css",
        "styles.css",
    ):
        resolved = _resolve_relative_zip_path("", candidate)
        if resolved not in stylesheet_candidates:
            stylesheet_candidates.append(resolved)

    return {
        "title": title,
        "author": author,
        "identifier": identifier,
        "language": language,
        "page_progression_direction": page_progression_direction,
        "asset_items": asset_items,
        "include_toc_page": include_toc_page,
        "info_candidates": info_candidates,
        "nav_candidates": nav_candidates,
        "ncx_candidates": ncx_candidates,
        "spine_page_candidates": spine_page_candidates,
        "stylesheet_candidates": stylesheet_candidates,
    }


def _collect_passthrough_files(
    zf: ZipFile,
    page_entry_names: list[str],
    *,
    excluded_entries: list[str] | None = None,
) -> dict[str, bytes]:
    generated_entries_lowers = {
        "mimetype",
        "meta-inf/container.xml",
        "oebps/content.opf",
        "oebps/styles.css",
        "oebps/info.xhtml",
        "oebps/nav.xhtml",
        "oebps/toc.ncx",
        *(name.lower() for name in page_entry_names),
    }
    if excluded_entries:
        generated_entries_lowers.update(entry.lower() for entry in excluded_entries if entry)
    return {
        name: zf.read(name)
        for name in zf.namelist()
        if not name.endswith("/") and name.lower() not in generated_entries_lowers
    }


def _zip_name_maps(zf: ZipFile) -> tuple[set[str], dict[str, str]]:
    names = zf.namelist()
    return set(names), {name.lower(): name for name in names}


def _find_zip_entry(
    candidate_names: list[str],
    zip_names: set[str],
    zip_names_by_lower: dict[str, str],
) -> str | None:
    for candidate in candidate_names:
        cleaned = candidate.strip().strip("/")
        if not cleaned:
            continue
        if cleaned in zip_names:
            return cleaned
        matched = zip_names_by_lower.get(cleaned.lower())
        if matched:
            return matched
    return None


def _read_zip_text(zf: ZipFile, entry_name: str) -> str:
    payload = zf.read(entry_name)
    try:
        return payload.decode()
    except UnicodeDecodeError:
        try:
            return etree.tostring(_parse_xml(payload), encoding="unicode")
        except etree.XMLSyntaxError:
            return payload.decode(errors="ignore")


def _read_optional_zip_text(zf: ZipFile, entry_name: str | None) -> str:
    if not entry_name:
        return ""
    try:
        return _read_zip_text(zf, entry_name)
    except KeyError:
        return ""


def _href_aliases(entry_name: str) -> set[str]:
    cleaned = entry_name.strip().strip("/")
    if not cleaned:
        return set()
    aliases = {cleaned.lower()}
    aliases.add(_relative_zip_path("OEBPS", cleaned).lower())
    if cleaned.lower().startswith("oebps/"):
        aliases.add(cleaned[6:].lower())
    return aliases


def _page_number_from_entry_name(entry_name: str, fallback_page_number: int) -> int:
    file_name = entry_name.rsplit("/", 1)[-1]
    match = PAGE_FILE_NUMBER_PATTERN.match(file_name)
    if not match:
        return fallback_page_number
    return int(match.group(1))


def _resolve_opf_entry_name(
    zf: ZipFile,
    zip_names: set[str],
    zip_names_by_lower: dict[str, str],
) -> str | None:
    container_entry = _find_zip_entry(["META-INF/container.xml"], zip_names, zip_names_by_lower)
    if container_entry:
        try:
            container_root = _parse_xml(_read_zip_text(zf, container_entry))
        except KeyError, etree.XMLSyntaxError, UnicodeDecodeError:
            container_root = None
        if container_root is not None:
            for element in container_root.iter():
                if _local_name(element.tag) != "rootfile":
                    continue
                full_path = str(element.attrib.get("full-path") or "").strip()
                if not full_path:
                    continue
                resolved = _find_zip_entry([full_path], zip_names, zip_names_by_lower)
                if resolved:
                    return resolved

    resolved_default = _find_zip_entry(
        ["OEBPS/content.opf", "content.opf"], zip_names, zip_names_by_lower
    )
    if resolved_default:
        return resolved_default
    return next((name for name in sorted(zip_names) if name.lower().endswith(".opf")), None)


def _parse_info_body(info_xhtml_text: str) -> str:
    try:
        root = _parse_xml(info_xhtml_text)
    except etree.XMLSyntaxError:
        return ""
    body = next((elem for elem in root.iter() if _local_name(elem.tag) == "body"), None)
    return _inner_xml(body) if body is not None else ""


def _href_to_toc_entry(href: str, text: str, *, base_dir: str = "") -> dict[str, Any] | None:
    path, fragment = href.strip().partition("#")[::2]
    normalized_href = _resolve_relative_zip_path(base_dir, path)
    if not normalized_href or normalized_href == ".":
        return None
    entry: dict[str, Any] = {"text": text.strip()}
    page_number = _page_number_from_entry_name(normalized_href, 0)
    if page_number > 0:
        entry["page"] = page_number
    else:
        entry["href"] = normalized_href
    anchor = (fragment or "").strip()
    if anchor:
        entry["anchor"] = anchor
    return entry


def _parse_toc_label_fragment(li_element: etree._Element) -> etree._Element:
    label_fragment = deepcopy(li_element)
    for child in list(label_fragment):
        if _local_name(child.tag) == "ol":
            label_fragment.remove(child)
    return label_fragment


def _parse_toc_label_data(li_element: etree._Element) -> tuple[etree._Element | None, str]:
    label_fragment = _parse_toc_label_fragment(li_element)
    anchor = next((child for child in label_fragment.iter() if _local_name(child.tag) == "a"), None)
    label_text = " ".join("".join(label_fragment.itertext()).split())
    return anchor, label_text


def _parse_toc_node(li_element: etree._Element, *, base_dir: str = "") -> list[Any]:
    child_list = next((child for child in list(li_element) if _local_name(child.tag) == "ol"), None)
    child_items: list[Any] = []
    if child_list is not None:
        for child_li in list(child_list):
            if _local_name(child_li.tag) == "li":
                child_items.extend(_parse_toc_node(child_li, base_dir=base_dir))

    anchor, label_text = _parse_toc_label_data(li_element)
    if anchor is None:
        if child_items:
            return [({"text": label_text}, child_items)]
        return child_items

    href = (anchor.attrib.get("href") or "").strip()
    anchor_text = "".join(anchor.itertext()).strip() or label_text
    entry = _href_to_toc_entry(href, anchor_text, base_dir=base_dir)
    if entry is None:
        if child_items:
            return [({"text": anchor_text}, child_items)]
        return child_items

    if child_items:
        return [(entry, child_items)]
    return [entry]


def _parse_nav_toc(nav_xhtml_text: str, *, nav_entry_name: str = "") -> list[Any]:
    try:
        root = _parse_xml(nav_xhtml_text)
    except etree.XMLSyntaxError:
        return []
    nav_elements = [elem for elem in root.iter() if _local_name(elem.tag) == "nav"]
    if not nav_elements:
        return []
    nav_element = next((elem for elem in nav_elements if _is_toc_nav(elem)), nav_elements[0])
    toc_list = next((elem for elem in list(nav_element) if _local_name(elem.tag) == "ol"), None)
    if toc_list is None:
        return []
    nav_base_dir = nav_entry_name.rsplit("/", 1)[0] if "/" in nav_entry_name else ""

    toc: list[Any] = []
    for li_element in list(toc_list):
        if _local_name(li_element.tag) != "li":
            continue
        toc.extend(_parse_toc_node(li_element, base_dir=nav_base_dir))
    return toc


def _parse_ncx_node(nav_point: etree._Element, *, base_dir: str = "") -> list[Any]:
    nav_label = next(
        (child for child in list(nav_point) if _local_name(child.tag) == "navlabel"), None
    )
    if nav_label is None:
        label = ""
    else:
        label_text = next(
            (child for child in nav_label.iter() if _local_name(child.tag) == "text"), None
        )
        label = (
            "".join(label_text.itertext()).strip()
            if label_text is not None
            else "".join(nav_label.itertext()).strip()
        )
    content = next(
        (child for child in list(nav_point) if _local_name(child.tag) == "content"), None
    )
    href = str(content.attrib.get("src") or "").strip() if content is not None else ""

    child_items: list[Any] = []
    for child in list(nav_point):
        if _local_name(child.tag) == "navpoint":
            child_items.extend(_parse_ncx_node(child, base_dir=base_dir))

    entry = _href_to_toc_entry(href, label, base_dir=base_dir)
    if entry is None:
        if child_items:
            return [({"text": label}, child_items)]
        return child_items
    return [(entry, child_items)] if child_items else [entry]


def _parse_ncx_toc(toc_ncx_text: str, *, ncx_entry_name: str = "") -> list[Any]:
    try:
        root = _parse_xml(toc_ncx_text)
    except etree.XMLSyntaxError:
        return []
    nav_map = next((elem for elem in root.iter() if _local_name(elem.tag) == "navmap"), None)
    if nav_map is None:
        return []
    ncx_base_dir = ncx_entry_name.rsplit("/", 1)[0] if "/" in ncx_entry_name else ""
    toc: list[Any] = []
    for nav_point in list(nav_map):
        if _local_name(nav_point.tag) != "navpoint":
            continue
        toc.extend(_parse_ncx_node(nav_point, base_dir=ncx_base_dir))
    return toc


def _resolve_toc_pages(toc: list[Any], page_by_href: dict[str, int]) -> list[Any]:  # noqa: C901
    resolved: list[Any] = []

    def first_page(items: list[Any]) -> int:
        for child_item in items:
            if _is_branch(child_item):
                child_entry, child_children = child_item
                child_page = _to_int(child_entry.get("page"), 0)
                if child_page > 0:
                    return child_page
                nested_page = first_page(child_children)
                if nested_page > 0:
                    return nested_page
                continue
            if isinstance(child_item, dict):
                child_page = _to_int(child_item.get("page"), 0)
                if child_page > 0:
                    return child_page
        return 0

    def resolve_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
        page = _to_int(entry.get("page"), 0)
        if page <= 0:
            href = str(entry.get("href") or "").strip().lower()
            page = page_by_href.get(href, 0)
        if page <= 0:
            return None
        out_entry = dict(entry)
        out_entry["page"] = page
        return out_entry

    for item in toc:
        if _is_branch(item):
            entry, children = item
            resolved_children = _resolve_toc_pages(children, page_by_href)
            resolved_entry = resolve_entry(entry)
            if resolved_entry is None:
                inferred_page = first_page(resolved_children)
                if inferred_page > 0:
                    resolved_entry = {**entry, "page": inferred_page}
            if resolved_entry is None:
                resolved.extend(resolved_children)
                continue
            resolved.append(
                (resolved_entry, resolved_children) if resolved_children else resolved_entry
            )
            continue
        if not isinstance(item, dict):
            continue
        resolved_entry = resolve_entry(item)
        if resolved_entry is None:
            continue
        resolved.append(resolved_entry)

    return resolved


def _is_branch(item: Any) -> bool:
    return (
        isinstance(item, (list, tuple))
        and len(item) == BRANCH_ITEM_SIZE
        and isinstance(item[0], dict)
        and isinstance(item[1], list)
    )


def _cut_toc(toc: list[Any], start_page: int, end_page: int) -> list[Any]:
    out: list[Any] = []
    for item in toc:
        if _is_branch(item):
            entry, children = item
            page = _to_int(entry.get("page"), 0)
            if page < start_page or page > end_page:
                out.extend(_cut_toc(children, start_page, end_page))
                continue
            trimmed_children = _cut_toc(children, start_page, end_page)
            out.append((entry, trimmed_children) if trimmed_children else entry)
            continue
        if not isinstance(item, dict):
            continue
        page = _to_int(item.get("page"), 0)
        if page < start_page:
            continue
        if page > end_page:
            continue
        out.append(item)
    return out


def _extract_headings(body: etree._Element) -> list[str]:
    titles: list[str] = []
    for element in body.iter():
        if _local_name(element.tag) not in HEADING_TAGS:
            continue
        title = "".join(element.itertext()).strip()
        if title and (not titles or titles[-1] != title):
            titles.append(title)
    return titles


def _parse_page_entry(
    entry_name: str,
    entry_text: str,
    *,
    fallback_page_number: int,
) -> dict[str, Any] | None:
    page_number = _page_number_from_entry_name(entry_name, fallback_page_number)
    try:
        root = _parse_xml(entry_text)
    except etree.XMLSyntaxError:
        return None
    body = next((elem for elem in root.iter() if _local_name(elem.tag) == "body"), None)
    if body is None:
        return None
    return {
        "page_number": page_number,
        "page": page_number,
        "text_html": _inner_xml(body),
        "page_titles": _extract_headings(body),
        "source_entry_name": entry_name,
    }


def _resolve_volume_groups(
    page_entries: list[dict[str, Any]],
    toc: list[Any],
) -> list[tuple[str, list[dict[str, Any]]]]:
    def top_level_toc_start_pages(toc_items: list[Any], max_page: int) -> list[int]:
        starts = sorted(
            [
                _to_int(
                    (item[0] if _is_branch(item) else item if isinstance(item, dict) else {}).get(
                        "page"
                    ),
                    0,
                )
                for item in toc_items
            ]
        )
        return [page for page in starts if 0 < page <= max_page]

    ordered_rows = sorted(page_entries, key=lambda row: int(row["page_number"]))
    if not ordered_rows:
        return []
    min_page = int(ordered_rows[0]["page_number"])
    max_page = int(ordered_rows[-1]["page_number"])
    top_level_starts = top_level_toc_start_pages(toc, max_page)
    if len(top_level_starts) <= 1:
        return []
    top_level_starts[0] = min(top_level_starts[0], min_page)

    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for index, start_page in enumerate(top_level_starts, start=1):
        next_start = top_level_starts[index] if index < len(top_level_starts) else max_page + 1
        pages = [row for row in ordered_rows if start_page <= int(row["page_number"]) < next_start]
        if pages:
            groups.append((str(index), pages))
    return groups if len(groups) > 1 else []


def _render_toc_items(toc: list[Any], page_map: dict[int, str], *, ncx: bool) -> str:
    nav_index = 0

    def render_item(item: Any) -> str:
        nonlocal nav_index
        if _is_branch(item):
            entry, children = item
        elif isinstance(item, dict):
            entry, children = item, []
        else:
            return ""

        page = _to_int(entry.get("page"), 0)
        href = str(entry.get("href") or "").strip()
        if page > 0 and page in page_map:
            href = page_map[page]
        elif not href:
            href = f"text/page_{page}.xhtml"
        anchor = str(entry.get("anchor") or "").strip()
        if anchor:
            href = f"{href}#{anchor}"
        text = _escape_xml(entry.get("text") or "")

        if not ncx:
            children_html = render_list(children) if children else ""
            return f'<li><a href="{href}">{text}</a>{children_html}</li>'

        item_id = f"nav_{nav_index}"
        nav_index += 1
        children_html = "".join(render_item(child) for child in children)
        return (
            f'<navPoint id="{item_id}"><navLabel><text>{text}</text></navLabel>'
            f'<content src="{href}"/>{children_html}</navPoint>'
        )

    def render_list(items: list[Any]) -> str:
        if not items:
            return ""
        return f"<ol>{''.join(render_item(item) for item in items)}</ol>"

    return "".join(render_item(item) for item in toc) if ncx else render_list(toc)


def _xhtml_document(  # noqa: PLR0913
    title: str,
    body: str,
    stylesheet_href: str,
    *,
    html_attrs: str = "",
    language: str,
    text_direction: str,
) -> str:
    attrs = f" {html_attrs}" if html_attrs else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml"{attrs} lang="{_escape_xml(language)}" dir="{_escape_xml(text_direction)}">\n'
        f'<head> <meta charset="utf-8" /><title>{_escape_xml(title)}</title>'
        f' <link rel="stylesheet" href="{stylesheet_href}" /> </head>\n'
        f"<body> {body} </body>\n</html>\n"
    )


def _build_epub_bytes(  # noqa: C901, PLR0912, PLR0915
    info: dict[str, Any],
    pages: list[dict[str, Any]],
    *,
    include_toc_page: bool,
    asset_items: list[dict[str, str]] | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    language = _split_language(str(info.get("language") or ""))
    labels = SPLIT_LABELS[language]
    title = str(info.get("title") or labels["fallback_title"])
    author = str(info.get("author") or "")
    page_progression_direction = _normalize_page_direction(
        str(info.get("page_progression_direction") or "")
    )
    text_direction = _infer_text_direction(language, page_progression_direction)
    if not page_progression_direction:
        page_progression_direction = text_direction
    identifier = str(info.get("local_identifier") or "").strip()
    if not identifier:
        identifier = f"urn:local:{uuid.uuid4()}"
    stylesheet_bytes = info.get("stylesheet_bytes")
    if isinstance(stylesheet_bytes, bytes):
        stylesheet_target = _resolve_relative_zip_path(
            "OEBPS", str(info.get("stylesheet_href") or "styles.css")
        )
        stylesheet_content: str | bytes = stylesheet_bytes
    else:
        stylesheet_target = "OEBPS/styles.css"
        stylesheet_content = BASE_CSS.strip()
    stylesheet_href = _relative_zip_path("OEBPS", stylesheet_target)
    text_stylesheet_href = _relative_zip_path("OEBPS/text", stylesheet_target)

    sorted_pages = sorted(pages, key=lambda p: int(p.get("page_number") or 0))
    max_page_number = int(sorted_pages[-1].get("page_number") or 0) if sorted_pages else 0
    zfill_length = len(str(max_page_number)) + 1

    page_chapters_raw = info.get("page_chapters")
    page_chapters: dict[int, list[Any]] = {}
    if isinstance(page_chapters_raw, dict):
        for key, value in page_chapters_raw.items():
            key_text = str(key)
            if key_text.isdigit() and isinstance(value, list):
                page_chapters[int(key_text)] = value

    page_entries: list[dict[str, Any]] = []
    for page in sorted_pages:
        page_number = _to_int(page.get("page_number"), 0)
        text_html = str(page.get("text_html") or "")
        file_name = f"page_1_{str(page_number).zfill(zfill_length)}.xhtml"
        page_title = str(page_chapters.get(page_number, [""])[0] or title)
        page_entries.append(
            {
                "page_number": page_number,
                "page": _to_int(page.get("page"), page_number),
                "file_name": file_name,
                "title": page_title,
                "content_html": text_html,
            }
        )

    page_map = {entry["page_number"]: f"text/{entry['file_name']}" for entry in page_entries}
    info_body = str(info.get("about") or "")

    toc_raw = info.get("toc")
    toc: list[Any] = toc_raw if isinstance(toc_raw, list) else []
    toc_html = (
        _render_toc_items(toc, page_map, ncx=False)
        if toc
        else (
            "<ol>"
            + "".join(
                f'<li><a href="{page_map.get(entry["page_number"], "text/page_" + str(entry["page_number"]) + ".xhtml")}">'
                f"{labels['page']} {entry['page']}</a></li>"
                for entry in page_entries
            )
            + "</ol>"
        )
    )

    info_link = f'<li><a href="info.xhtml">{_escape_xml(labels["book_info"])}</a></li>'
    nav_link = f'<li><a href="nav.xhtml">{_escape_xml(labels["toc"])}</a></li>'
    if toc_html.startswith("<ol>"):
        nav_items = toc_html.replace("<ol>", f"<ol>{info_link}{nav_link}", 1)
    else:
        nav_items = f"<ol>{info_link}{nav_link}</ol>"

    ncx_toc = toc or [
        {"page": entry["page_number"], "text": f"{labels['page']} {entry['page']}"}
        for entry in page_entries
    ]
    ncx_items = _render_toc_items(ncx_toc, page_map, ncx=True)

    modified = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    manifest_items = "".join(
        f'<item id="p{entry["page_number"]}" href="text/{entry["file_name"]}" media-type="application/xhtml+xml" />'
        for entry in page_entries
    )
    manifest_asset_items = ""
    if asset_items:
        kept_items: list[str] = []
        for idx, item in enumerate(asset_items, start=1):
            href = str(item.get("href") or "").strip()
            media_type = str(item.get("media_type") or "").strip()
            if not href or not media_type:
                continue
            if _resolve_relative_zip_path("OEBPS", href) == stylesheet_target:
                continue
            properties = str(item.get("properties") or "").strip()
            properties_attr = f' properties="{_escape_xml(properties)}"' if properties else ""
            kept_items.append(
                f'<item id="a{idx}" href="{_escape_xml(href)}" media-type="{_escape_xml(media_type)}"{properties_attr} />'
            )
        manifest_asset_items = " " + " ".join(kept_items) if kept_items else ""
    spine_items = "".join(f'<itemref idref="p{entry["page_number"]}" />' for entry in page_entries)
    nav_itemref = '<itemref idref="nav" />' if include_toc_page else ""

    content_opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"> '
        f'<dc:identifier id="bookid">{_escape_xml(identifier)}</dc:identifier>'
        f"<dc:title>{_escape_xml(title)}</dc:title>"
        f"{'<dc:creator>' + _escape_xml(author) + '</dc:creator>' if author else ''}"
        f'<dc:language>{_escape_xml(language)}</dc:language><meta property="dcterms:modified">{modified}</meta> </metadata>\n'
        '<manifest> <item id="info" href="info.xhtml" media-type="application/xhtml+xml" />'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />'
        f'<item id="css" href="{_escape_xml(stylesheet_href)}" media-type="text/css" /> {manifest_items}{manifest_asset_items} </manifest>\n'
        f'<spine toc="ncx" page-progression-direction="{_escape_xml(page_progression_direction)}"> '
        f'<itemref idref="info" /> {nav_itemref} {spine_items} </spine></package>\n'
    )

    nav_xhtml = _xhtml_document(
        title,
        f'<nav epub:type="toc" id="toc"> <h1>{_escape_xml(labels["toc"])}</h1> {nav_items} </nav>',
        stylesheet_href,
        html_attrs='xmlns:epub="http://www.idpf.org/2007/ops"',
        language=language,
        text_direction=text_direction,
    )

    toc_ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head> <meta content="{_escape_xml(identifier)}" name="dtb:uid"/><meta content="0" name="dtb:depth"/>'
        '<meta content="0" name="dtb:totalPageCount"/><meta content="0" name="dtb:maxPageNumber"/> </head>\n'
        f"<docTitle> <text>{_escape_xml(title)}</text> </docTitle>\n"
        f'<navMap> <navPoint id="info"> <navLabel> <text>{_escape_xml(labels["book_info"])}</text> </navLabel>'
        ' <content src="info.xhtml"/> </navPoint><navPoint id="nav"> '
        f'<navLabel> <text>{_escape_xml(labels["toc"])}</text> </navLabel><content src="nav.xhtml" /> </navPoint>'
        f"{ncx_items} </navMap></ncx>\n"
    )

    container_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        ' <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />'
        " </rootfiles></container>\n"
    )

    info_xhtml = _xhtml_document(
        labels["book_info"],
        info_body,
        stylesheet_href,
        language=language,
        text_direction=text_direction,
    )

    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED, compresslevel=9) as zf:
        mime_info = ZipInfo("mimetype")
        mime_info.compress_type = ZIP_STORED
        zf.writestr(mime_info, "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr(stylesheet_target, stylesheet_content)
        zf.writestr("OEBPS/info.xhtml", info_xhtml)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/toc.ncx", toc_ncx)
        zf.writestr("OEBPS/content.opf", content_opf)
        for entry in page_entries:
            page_html_attrs = (
                'xmlns:epub="http://www.idpf.org/2007/ops"'
                if "epub:type=" in entry["content_html"]
                else ""
            )
            zf.writestr(
                f"OEBPS/text/{entry['file_name']}",
                _xhtml_document(
                    entry["title"] or title,
                    entry["content_html"],
                    text_stylesheet_href,
                    html_attrs=page_html_attrs,
                    language=language,
                    text_direction=text_direction,
                ),
            )
        if extra_files:
            generated_names = {
                "mimetype",
                "META-INF/container.xml",
                stylesheet_target,
                "OEBPS/info.xhtml",
                "OEBPS/nav.xhtml",
                "OEBPS/toc.ncx",
                "OEBPS/content.opf",
                *(f"OEBPS/text/{entry['file_name']}" for entry in page_entries),
            }
            for file_name, file_bytes in extra_files.items():
                if file_name in generated_names:
                    continue
                zf.writestr(file_name, file_bytes)

    return buf.getvalue()


def _resolve_split_page_entry_names(
    metadata: dict[str, Any],
    zip_names: set[str],
    zip_names_by_lower: dict[str, str],
) -> list[str]:
    page_entry_names: list[str] = []
    for href in metadata.get("spine_page_candidates") or []:
        matched = _find_zip_entry([str(href)], zip_names, zip_names_by_lower)
        if matched and matched not in page_entry_names:
            page_entry_names.append(matched)
    if page_entry_names:
        return page_entry_names
    return sorted(
        name for name in zip_names if "/text/" in name.lower() and name.lower().endswith(".xhtml")
    )


def _parse_split_page_entries(zf: ZipFile, page_entry_names: list[str]) -> list[dict[str, Any]]:
    page_entries: list[dict[str, Any]] = []
    for index, entry_name in enumerate(page_entry_names, start=1):
        page_text = _read_optional_zip_text(zf, entry_name)
        if not page_text:
            continue
        parsed = _parse_page_entry(entry_name, page_text, fallback_page_number=index)
        if parsed:
            page_entries.append(parsed)
    return page_entries


def _resolve_split_resource_entries(
    metadata: dict[str, Any],
    zip_names: set[str],
    zip_names_by_lower: dict[str, str],
) -> dict[str, str | None]:
    return {
        "info_entry_name": _find_zip_entry(
            metadata.get("info_candidates") or [], zip_names, zip_names_by_lower
        ),
        "nav_entry_name": _find_zip_entry(
            metadata.get("nav_candidates") or [], zip_names, zip_names_by_lower
        ),
        "ncx_entry_name": _find_zip_entry(
            metadata.get("ncx_candidates") or [], zip_names, zip_names_by_lower
        ),
        "stylesheet_entry_name": _find_zip_entry(
            metadata.get("stylesheet_candidates") or [], zip_names, zip_names_by_lower
        ),
    }


def _resolve_split_toc(
    page_entries: list[dict[str, Any]],
    nav_xhtml: str,
    nav_entry_name: str | None,
    toc_ncx: str,
    ncx_entry_name: str | None,
) -> list[Any]:
    def top_level_toc_start_pages(toc_items: list[Any], max_page: int) -> list[int]:
        starts = sorted(
            [
                _to_int(
                    (item[0] if _is_branch(item) else item if isinstance(item, dict) else {}).get(
                        "page"
                    ),
                    0,
                )
                for item in toc_items
            ]
        )
        return [page for page in starts if 0 < page <= max_page]

    page_by_href: dict[str, int] = {}
    for row in page_entries:
        page_number = int(row["page_number"])
        source_name = str(row.get("source_entry_name") or "")
        for alias in _href_aliases(source_name):
            page_by_href.setdefault(alias, page_number)

    max_page = max((int(row["page_number"]) for row in page_entries), default=0)
    nav_toc = _parse_nav_toc(nav_xhtml, nav_entry_name=nav_entry_name or "") if nav_xhtml else []
    resolved_nav_toc = _resolve_toc_pages(nav_toc, page_by_href) if nav_toc else []
    ncx_toc = _parse_ncx_toc(toc_ncx, ncx_entry_name=ncx_entry_name or "") if toc_ncx else []
    resolved_ncx_toc = _resolve_toc_pages(ncx_toc, page_by_href) if ncx_toc else []

    if resolved_nav_toc and resolved_ncx_toc:
        nav_starts = top_level_toc_start_pages(resolved_nav_toc, max_page)
        ncx_starts = top_level_toc_start_pages(resolved_ncx_toc, max_page)
        if len(ncx_starts) > len(nav_starts):
            return resolved_ncx_toc

    if resolved_nav_toc:
        return resolved_nav_toc
    return resolved_ncx_toc


def _filter_split_asset_items(
    metadata: dict[str, Any],
    page_entry_names: list[str],
) -> list[dict[str, Any]]:
    page_entry_lowers = {name.lower() for name in page_entry_names}
    return [
        item
        for item in list(metadata.get("asset_items") or [])
        if _resolve_relative_zip_path("OEBPS", str(item.get("href") or "")).lower()
        not in page_entry_lowers
    ]


def split_epub_by_volumes(epub_path: Path, out_dir: Path) -> list[Path]:
    with ZipFile(epub_path) as zf:
        zip_names, zip_names_by_lower = _zip_name_maps(zf)
        opf_entry_name = _resolve_opf_entry_name(zf, zip_names, zip_names_by_lower)
        if not opf_entry_name:
            return []
        try:
            opf_text = _read_zip_text(zf, opf_entry_name)
            metadata = _parse_content_opf(opf_text, opf_entry_name)
        except KeyError, etree.XMLSyntaxError, UnicodeDecodeError:
            return []
        page_entry_names = _resolve_split_page_entry_names(metadata, zip_names, zip_names_by_lower)
        if not page_entry_names:
            return []

        page_entries = _parse_split_page_entries(zf, page_entry_names)
        if not page_entries:
            return []

        source_entries = _resolve_split_resource_entries(metadata, zip_names, zip_names_by_lower)
        info_entry_name = source_entries["info_entry_name"]
        nav_entry_name = source_entries["nav_entry_name"]
        ncx_entry_name = source_entries["ncx_entry_name"]
        stylesheet_entry_name = source_entries["stylesheet_entry_name"]

        info_xhtml = _read_optional_zip_text(zf, info_entry_name)
        nav_xhtml = _read_optional_zip_text(zf, nav_entry_name)
        toc_ncx = _read_optional_zip_text(zf, ncx_entry_name)
        stylesheet_bytes = zf.read(stylesheet_entry_name) if stylesheet_entry_name else None

        passthrough_files = _collect_passthrough_files(
            zf,
            page_entry_names,
            excluded_entries=[
                opf_entry_name,
                info_entry_name or "",
                nav_entry_name or "",
                ncx_entry_name or "",
            ],
        )

        about_html = _parse_info_body(info_xhtml) if info_xhtml else ""
        toc = _resolve_split_toc(page_entries, nav_xhtml, nav_entry_name, toc_ncx, ncx_entry_name)
        grouped_pages = _resolve_volume_groups(page_entries, toc)
        if not grouped_pages:
            return []
        asset_items = _filter_split_asset_items(metadata, page_entry_names)

    out_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[Path] = []
    for volume_name, pages_in_volume in grouped_pages:
        start_page = int(pages_in_volume[0]["page_number"])
        end_page = int(pages_in_volume[-1]["page_number"])

        page_chapters = {
            int(row["page_number"]): list(row["page_titles"])
            for row in pages_in_volume
            if row["page_titles"]
        }
        info_obj: dict[str, Any] = {
            "title": f"{metadata['title']} - {volume_name}".strip(),
            "author": str(metadata["author"]),
            "language": str(metadata.get("language") or ""),
            "page_progression_direction": str(metadata.get("page_progression_direction") or ""),
            "about": about_html,
            "toc": _cut_toc(toc, start_page, end_page),
            "page_chapters": page_chapters,
            "stylesheet_href": (
                _relative_zip_path("OEBPS", stylesheet_entry_name)
                if stylesheet_entry_name
                else "styles.css"
            ),
            "stylesheet_bytes": stylesheet_bytes,
        }
        if metadata["identifier"]:
            info_obj["local_identifier"] = str(metadata["identifier"])

        pages_payload = [
            {
                "page_number": row["page_number"],
                "page": row["page"],
                "text_html": str(row["text_html"]),
            }
            for row in pages_in_volume
        ]
        epub_bytes = _build_epub_bytes(
            info_obj,
            pages_payload,
            include_toc_page=metadata["include_toc_page"],
            asset_items=asset_items,
            extra_files=passthrough_files,
        )

        output_name = _sanitize_filename(f"{epub_path.stem} - {volume_name}.epub")
        output_path = out_dir / output_name
        output_path.write_bytes(epub_bytes)
        written_files.append(output_path)

    return written_files
