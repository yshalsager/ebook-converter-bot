import posixpath
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from lxml import etree, html

from ebook_converter_bot.utils.epub_footnotes import (
    append_to_last_footnote,
    pop_leading_continuation,
    update_hamesh_html,
)

xml_parser = etree.XMLParser(resolve_entities=False)
page_id_re = re.compile(r"page_(\d+)")


def _ns(root: etree._Element) -> str:
    return root.tag.split("}")[0] + "}" if "}" in root.tag else ""


def _pick_valid_opf(epub_book: ZipFile) -> tuple[ZipInfo, bytes, etree._Element] | None:
    opf_infos = [i for i in epub_book.infolist() if i.filename.endswith(".opf")]
    for info in reversed(opf_infos):
        with epub_book.open(info, "r") as f:
            data = f.read()
        try:
            root = etree.fromstring(data, xml_parser)
        except etree.ParseError:
            continue
        namespace = _ns(root)
        if (
            root.find(f".//{namespace}manifest") is None
            or root.find(f".//{namespace}spine") is None
        ):
            continue
        return info, data, root
    return None


def _href_resolveds(opf_dir: str, href: str) -> tuple[list[str], str]:
    base, _, frag = href.partition("#")
    base = base.removeprefix("./")
    resolveds: list[str] = []
    for candidate in ([posixpath.join(opf_dir, base)] if opf_dir else []) + [base]:
        resolved = posixpath.normpath(candidate)
        if resolved not in resolveds:
            resolveds.append(resolved)
    return resolveds, frag


def _href_exists(zip_names: set[str], opf_dir: str, href: str) -> bool:
    resolveds, _ = _href_resolveds(opf_dir, href)
    return any(r in zip_names for r in resolveds)


def _fix_href_case(
    zip_names: set[str], zip_lower_map: dict[str, list[str]], opf_dir: str, href: str
) -> str:
    resolveds, frag = _href_resolveds(opf_dir, href)
    if any(r in zip_names for r in resolveds):
        return href
    for resolved in resolveds:
        candidates = zip_lower_map.get(resolved.lower())
        if not candidates or len(candidates) != 1:
            continue
        actual = candidates[0]
        rel = (
            posixpath.relpath(actual, opf_dir)
            if opf_dir and actual.startswith(f"{opf_dir}/")
            else actual
        )
        rel = rel.removeprefix("./")
        return f"{rel}#{frag}" if frag else rel
    return href


def _reorder_pages(parent: etree._Element, namespace: str, tag_name: str, attr: str) -> None:
    all_children = list(parent)
    targets: list[tuple[int, etree._Element]] = []
    for child in all_children:
        if child.tag != f"{namespace}{tag_name}":
            continue
        match = page_id_re.fullmatch(child.get(attr, ""))
        if match:
            targets.append((int(match.group(1)), child))
    if not targets:
        return

    sorted_targets = [c for _, c in sorted(targets, key=lambda x: x[0])]
    target_set = {c for _, c in targets}
    it = iter(sorted_targets)
    new_children = [next(it) if c in target_set else c for c in all_children]

    for child in all_children:
        parent.remove(child)
    for child in new_children:
        parent.append(child)


def _normalize_manifest(
    manifest: etree._Element,
    namespace: str,
    zip_names: set[str],
    zip_lower_map: dict[str, list[str]],
    opf_dir: str,
) -> dict[str, etree._Element]:
    manifest_by_id: dict[str, etree._Element] = {}
    for item in [c for c in list(manifest) if c.tag == f"{namespace}item"]:
        item_id = item.get("id")
        if not item_id:
            continue

        href = item.get("href")
        if href:
            item.set("href", _fix_href_case(zip_names, zip_lower_map, opf_dir, href))

        prev = manifest_by_id.get(item_id)
        if prev is None:
            manifest_by_id[item_id] = item
            continue

        prev_href = prev.get("href")
        curr_href = item.get("href")
        prev_ok = bool(prev_href and _href_exists(zip_names, opf_dir, prev_href))
        curr_ok = bool(curr_href and _href_exists(zip_names, opf_dir, curr_href))
        keep = prev if prev_ok and not curr_ok else item
        drop = item if keep is prev else prev
        manifest.remove(drop)
        manifest_by_id[item_id] = keep

    for item_id, item in list(manifest_by_id.items()):
        href = item.get("href")
        if not href or _href_exists(zip_names, opf_dir, href):
            continue
        resolveds, _ = _href_resolveds(opf_dir, href)
        if any("/text/" in ("/" + r).lower() for r in resolveds):
            manifest.remove(item)
            manifest_by_id.pop(item_id, None)

    _reorder_pages(manifest, namespace, "item", "id")
    return manifest_by_id


def _normalize_spine(
    spine: etree._Element, namespace: str, manifest_by_id: dict[str, etree._Element]
) -> set[str]:
    seen_idref: set[str] = set()
    for itemref in [c for c in list(spine) if c.tag == f"{namespace}itemref"]:
        idref = itemref.get("idref")
        if not idref or idref in seen_idref or idref not in manifest_by_id:
            spine.remove(itemref)
            continue
        seen_idref.add(idref)
    return seen_idref


def _prepend_front_matter(
    spine: etree._Element,
    namespace: str,
    manifest_by_id: dict[str, etree._Element],
    seen_idref: set[str],
    href_exists: Callable[[str], bool],
) -> None:
    spine_children = list(spine)
    first_page_idx = next(
        (
            idx
            for idx, c in enumerate(spine_children)
            if c.tag == f"{namespace}itemref" and c.get("idref", "").startswith("page_")
        ),
        len(spine_children),
    )
    for front_id in ["titlepage", "intro", "book_info"]:
        if front_id in seen_idref or front_id not in manifest_by_id:
            continue
        href = manifest_by_id[front_id].get("href")
        if href and href_exists(href):
            spine.insert(first_page_idx, etree.Element(f"{namespace}itemref", {"idref": front_id}))
            first_page_idx += 1
            seen_idref.add(front_id)


def _unique_infos(infos: list[ZipInfo]) -> list[ZipInfo]:
    seen: set[str] = set()
    unique: list[ZipInfo] = []
    for info in reversed(infos):
        if info.filename in seen:
            continue
        seen.add(info.filename)
        unique.append(info)
    unique.reverse()
    return unique


def _needs_cleanup(epub_book: ZipFile, unique_infos: list[ZipInfo], total_infos: int) -> bool:
    if len(unique_infos) != total_infos:
        return True
    return (
        "mimetype" in epub_book.namelist()
        and epub_book.getinfo("mimetype").compress_type != ZIP_STORED
    )


def _body_inner_html(body: etree._Element) -> str:
    parts: list[str] = [body.text or ""]
    for child in list(body):
        parts.append(etree.tostring(child, encoding="unicode", with_tail=False))
        parts.append(child.tail or "")
    return "".join(parts)


def _set_body_inner_html(body: etree._Element, fragment: str) -> bool:
    try:
        wrapper = etree.fromstring(
            f'<wrapper xmlns:epub="http://www.idpf.org/2007/ops">{fragment}</wrapper>',
            xml_parser,
        )
    except etree.ParseError:
        return False

    for child in list(body):
        body.remove(child)
    body.text = wrapper.text
    for child in list(wrapper):
        wrapper.remove(child)
        body.append(child)
    return True


def _resolve_href_to_zip_name(
    zip_names: set[str], zip_lower_map: dict[str, list[str]], opf_dir: str, href: str
) -> str | None:
    fixed_href = _fix_href_case(zip_names, zip_lower_map, opf_dir, href)
    resolveds, _ = _href_resolveds(opf_dir, fixed_href)
    for resolved in resolveds:
        if resolved in zip_names:
            return resolved
        candidates = zip_lower_map.get(resolved.lower())
        if candidates and len(candidates) == 1:
            return candidates[0]
    return None


def _ordered_xhtml_paths(  # noqa: C901
    epub_book: ZipFile, content_opf: ZipInfo, root: etree._Element, unique_infos: list[ZipInfo]
) -> list[str]:
    namespace = _ns(root)
    manifest = root.find(f".//{namespace}manifest")
    spine = root.find(f".//{namespace}spine")
    if manifest is None or spine is None:
        return [
            info.filename
            for info in unique_infos
            if info.filename.lower().endswith((".xhtml", ".html", ".htm"))
        ]

    opf_dir = posixpath.dirname(content_opf.filename)
    zip_names = set(epub_book.namelist())
    zip_lower_map: dict[str, list[str]] = {}
    for name in zip_names:
        zip_lower_map.setdefault(name.lower(), []).append(name)

    manifest_href_by_id: dict[str, str] = {}
    for item in [child for child in list(manifest) if child.tag == f"{namespace}item"]:
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type", "").lower()
        if not item_id or not href:
            continue
        if media_type and "xhtml" not in media_type and "html" not in media_type:
            continue
        manifest_href_by_id[item_id] = href

    ordered: list[str] = []
    for itemref in [child for child in list(spine) if child.tag == f"{namespace}itemref"]:
        idref = itemref.get("idref")
        href = manifest_href_by_id.get(idref or "")
        if not href:
            continue
        resolved = _resolve_href_to_zip_name(zip_names, zip_lower_map, opf_dir, href)
        if resolved and resolved not in ordered:
            ordered.append(resolved)

    for info in unique_infos:
        lower = info.filename.lower()
        if not lower.endswith((".xhtml", ".html", ".htm")):
            continue
        if info.filename not in ordered:
            ordered.append(info.filename)
    return ordered


def _rewrite_epub_dedup(
    input_file: Path,
    epub_book: ZipFile,
    unique_infos: list[ZipInfo],
    replacements: dict[str, bytes],
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=str(input_file.parent), suffix=input_file.suffix, delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with ZipFile(tmp_path, "w", compression=ZIP_DEFLATED) as out:
            if any(i.filename == "mimetype" for i in unique_infos):
                out.writestr("mimetype", epub_book.read("mimetype"), compress_type=ZIP_STORED)
            for info in unique_infos:
                if info.filename == "mimetype":
                    continue
                if info.filename in replacements:
                    out.writestr(info, replacements[info.filename])
                else:
                    out.writestr(info, epub_book.read(info.filename))
        tmp_path.replace(input_file)
    finally:
        tmp_path.unlink(missing_ok=True)


def set_epub_to_rtl(input_file: Path) -> bool:
    with ZipFile(input_file, "r") as epub_book:
        picked = _pick_valid_opf(epub_book)
        if not picked:
            return False

        content_opf, opf_bytes, root = picked
        namespace = _ns(root)
        spine = root.find(f".//{namespace}spine")
        if spine is None:
            return False

        changed = False
        if spine.get("page-progression-direction") != "rtl":
            spine.set("page-progression-direction", "rtl")
            changed = True

        rtl_prefix = b"* {direction: rtl !important;}\n"
        replacements: dict[str, bytes] = {}
        infos = epub_book.infolist()
        unique_infos = _unique_infos(infos)
        needs_cleanup = _needs_cleanup(epub_book, unique_infos, len(infos))

        for info in unique_infos:
            if not info.filename.endswith(".css"):
                continue
            css = epub_book.read(info.filename)
            if b"direction: rtl !important" in css[:300].lower():
                continue
            replacements[info.filename] = rtl_prefix + css
            changed = True

        if not changed and not needs_cleanup:
            return False

        xml_declaration = opf_bytes.lstrip().startswith(b"<?xml")
        replacements[content_opf.filename] = (
            etree.tostring(root, encoding="utf-8", xml_declaration=xml_declaration)
            if changed
            else opf_bytes
        )
        _rewrite_epub_dedup(input_file, epub_book, unique_infos, replacements)
        return True


def standardize_epub_footnotes(input_file: Path) -> bool:  # noqa: C901,PLR0912,PLR0915
    with ZipFile(input_file, "r") as epub_book:
        picked = _pick_valid_opf(epub_book)
        if not picked:
            return False

        content_opf, _opf_bytes, root = picked
        infos = epub_book.infolist()
        unique_infos = _unique_infos(infos)
        needs_cleanup = _needs_cleanup(epub_book, unique_infos, len(infos))

        ordered_xhtml_paths = _ordered_xhtml_paths(epub_book, content_opf, root, unique_infos)
        if not ordered_xhtml_paths and not needs_cleanup:
            return False

        doc_states: list[dict[str, object]] = []
        for name in ordered_xhtml_paths:
            old = epub_book.read(name)
            try:
                doc_root = etree.fromstring(old, xml_parser)
            except etree.ParseError:
                continue
            namespace = _ns(doc_root)
            body = doc_root.find(f".//{namespace}body")
            if body is None:
                continue
            original_body = _body_inner_html(body)
            doc_states.append(
                {
                    "name": name,
                    "old": old,
                    "root": doc_root,
                    "body": body,
                    "original_body": original_body,
                    "new_body": original_body,
                }
            )

        for index, state in enumerate(doc_states):
            transformed = update_hamesh_html(str(state["new_body"]))
            stripped, continuation = pop_leading_continuation(transformed)
            if continuation and index > 0:
                previous_body = str(doc_states[index - 1]["new_body"])
                merged_previous, merged = append_to_last_footnote(previous_body, continuation)
                if merged:
                    doc_states[index - 1]["new_body"] = merged_previous
                    transformed = stripped
            state["new_body"] = transformed

        replacements: dict[str, bytes] = {}
        for state in doc_states:
            original_body = str(state["original_body"])
            new_body = str(state["new_body"])
            if new_body == original_body:
                continue
            body = state["body"]
            if not isinstance(body, etree._Element):
                continue
            if not _set_body_inner_html(body, new_body):
                continue
            old_bytes = state["old"]
            if not isinstance(old_bytes, bytes):
                continue
            xml_declaration = old_bytes.lstrip().startswith(b"<?xml")
            root_elem = state["root"]
            if not isinstance(root_elem, etree._Element):
                continue
            new_content = etree.tostring(
                root_elem,
                encoding="utf-8",
                xml_declaration=xml_declaration,
            )
            name = state["name"]
            if isinstance(name, str) and new_content != old_bytes:
                replacements[name] = new_content

        if not replacements and not needs_cleanup:
            return False

        _rewrite_epub_dedup(input_file, epub_book, unique_infos, replacements)
        return True


def fix_content_opf_problems(input_file: Path) -> None:
    with ZipFile(input_file, "r") as epub_book:
        picked = _pick_valid_opf(epub_book)
        if not picked:
            return

        content_opf, opf_bytes, root = picked
        namespace = _ns(root)

        manifest = root.find(f".//{namespace}manifest")
        spine = root.find(f".//{namespace}spine")
        if manifest is None or spine is None:
            return

        opf_dir = posixpath.dirname(content_opf.filename)
        zip_names = set(epub_book.namelist())
        zip_lower_map: dict[str, list[str]] = {}
        for name in zip_names:
            zip_lower_map.setdefault(name.lower(), []).append(name)

        manifest_by_id = _normalize_manifest(manifest, namespace, zip_names, zip_lower_map, opf_dir)
        seen_idref = _normalize_spine(spine, namespace, manifest_by_id)
        _prepend_front_matter(
            spine,
            namespace,
            manifest_by_id,
            seen_idref,
            lambda href: _href_exists(zip_names, opf_dir, href),
        )
        _reorder_pages(spine, namespace, "itemref", "idref")

        xml_declaration = opf_bytes.lstrip().startswith(b"<?xml")
        new_content = etree.tostring(root, encoding="utf-8", xml_declaration=xml_declaration)
        _rewrite_epub_dedup(
            input_file,
            epub_book,
            _unique_infos(epub_book.infolist()),
            {content_opf.filename: new_content},
        )


def _flatten_ncx_toc(nav_map: etree._Element, namespace: str) -> list[etree._Element]:
    def walk(nav_point: etree._Element) -> list[etree._Element]:
        points = [nav_point]
        for child in nav_point:
            if child.tag == f"{namespace}navPoint":
                points.extend(walk(child))
        return points

    points: list[etree._Element] = []
    for child in nav_map:
        if child.tag == f"{namespace}navPoint":
            points.extend(walk(child))

    flattened_items: list[etree._Element] = []
    for play_order, nav_point in enumerate(points, start=1):
        new_nav_point = etree.Element(
            f"{namespace}navPoint" if namespace else "navPoint",
            {"id": f"num_{play_order}", "playOrder": str(play_order)},
        )
        for child in list(nav_point):
            if child.tag != f"{namespace}navPoint":
                new_nav_point.append(child)
        flattened_items.append(new_nav_point)

    return flattened_items


def _flatten_html_nav(html_nav_file: bytes) -> bytes:
    root = html.fromstring(html_nav_file)
    nav = next(
        iter(
            root.xpath(
                '//nav[@role="doc-toc" or @id="toc" or contains(concat(" ", normalize-space(@class), " "), " toc ") or @*[name()="epub:type" and .="toc"]]'
            )
        ),
        None,
    )
    if nav is None:
        nav = next(iter(root.xpath("//nav")), None)
    if nav is None:
        return html_nav_file

    toc_ol = next(iter(nav.xpath(".//ol")), None)
    if toc_ol is None:
        return html_nav_file

    changed = False
    while True:
        li_with_ol = toc_ol.xpath(".//li[./ol]")
        if not li_with_ol:
            break
        parent_li = li_with_ol[-1]
        nested_ol = next(iter(parent_li.xpath("./ol")), None)
        if nested_ol is None:
            break
        child_lis = list(nested_ol.xpath("./li"))
        parent_ol = parent_li.getparent()
        if parent_ol is None:
            break
        insert_at = parent_ol.index(parent_li) + 1
        for child_li in child_lis:
            parent_ol.insert(insert_at, child_li)
            insert_at += 1
        parent_li.remove(nested_ol)
        changed = True

    return etree.tostring(root, encoding="utf-8") if changed else html_nav_file


def _flatten_toc_replacements(epub_book: ZipFile, unique_infos: list[ZipInfo]) -> dict[str, bytes]:
    replacements: dict[str, bytes] = {}

    toc_info = next((i for i in unique_infos if i.filename.endswith("toc.ncx")), None)
    if toc_info:
        old = epub_book.read(toc_info.filename)
        try:
            root = etree.fromstring(old, xml_parser)
        except etree.ParseError:
            root = None
        if root is not None:
            namespace = _ns(root)
            nav_map = root.find(f".//{namespace}navMap")
            if nav_map is not None and nav_map.getparent() is not None:
                new_nav_map = etree.Element(nav_map.tag, nav_map.attrib)
                for p in _flatten_ncx_toc(nav_map, namespace):
                    new_nav_map.append(p)
                parent = nav_map.getparent()
                idx = parent.index(nav_map)
                parent.remove(nav_map)
                parent.insert(idx, new_nav_map)
                xml_declaration = old.lstrip().startswith(b"<?xml")
                new = etree.tostring(root, encoding="utf-8", xml_declaration=xml_declaration)
                if new != old:
                    replacements[toc_info.filename] = new

    nav_info = next((i for i in unique_infos if i.filename.endswith("nav.xhtml")), None)
    if nav_info:
        old = epub_book.read(nav_info.filename)
        new = _flatten_html_nav(old)
        if new != old:
            replacements[nav_info.filename] = new

    return replacements


def flatten_toc(input_file: Path) -> None:
    with ZipFile(input_file, "r") as epub_book:
        infos = epub_book.infolist()
        unique_infos = _unique_infos(infos)
        if not any(
            i.filename.endswith("toc.ncx") or i.filename.endswith("nav.xhtml") for i in unique_infos
        ):
            return

        needs_cleanup = _needs_cleanup(epub_book, unique_infos, len(infos))

        replacements = _flatten_toc_replacements(epub_book, unique_infos)
        if not replacements and not needs_cleanup:
            return

        _rewrite_epub_dedup(input_file, epub_book, unique_infos, replacements)
