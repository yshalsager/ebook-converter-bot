# Shamela old .bok (Jet/Access MDB) -> EPUB converter.
# Kept intentionally dependency-light and sync; callers can run it in a thread.

from __future__ import annotations

import re
import uuid
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from access_parser import AccessParser

from ebook_converter_bot.utils.epub_common import escape_xml

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
HIGH_LATIN_RE = re.compile(r"[\u00C0-\u00FF]")
LOOKS_LIKE_HTML_RE = re.compile(r"</?(p|br|div|span|h[1-6]|font)\b", re.IGNORECASE)
VOID_TAG_RE = re.compile(
    r"<(br|hr|img|input|meta|link|area|base|col|embed|source|track|wbr)(\s[^>]*)?\/?>",
    re.IGNORECASE,
)
NUMBERED_SPLIT_RE = re.compile(
    r"(?=(?:^|[\s\u00A0])(?:[0-9]{1,4}|[\u0660-\u0669]{1,4}|[\u06F0-\u06F9]{1,4})\s*[-\u2013\u2014]\s+)"
)
NUMBERED_LINE_RE = re.compile(r"^(?:[0-9\u0660-\u0669\u06F0-\u06F9]{1,4})\s*[-\u2013\u2014]\s+")
TAG_RE = re.compile(r"<[^>]+>")

PREVIEW_ROWS = 80
UTF16_MIN_BYTES = 16
UTF16_NULL_RATIO = 0.25
LONG_LINE_LEN = 220
MIN_SPLIT_PARTS = 2
SNIPPET_LINES = 2
MAX_AUTO_TOC_TITLE_LEN = 100
PAIR_LEN = 2


@dataclass(frozen=True, slots=True)
class ContentCols:
    text: str
    id: str | None
    page: str | None
    part: str | None


@dataclass(frozen=True, slots=True)
class EpubBook:
    title: str
    author: str
    about: str
    pages: list[dict[str, Any]]
    toc_tree: list[Any]


def digits_to_ascii(v: object) -> str:
    s = str(v)
    s = re.sub(r"[\u0660-\u0669]", lambda m: str(ord(m.group(0)) - 0x0660), s)
    return re.sub(r"[\u06F0-\u06F9]", lambda m: str(ord(m.group(0)) - 0x06F0), s)


def fix_arabic_mojibake(value: str) -> str:
    if ARABIC_RE.search(value):
        return value
    hi = len(HIGH_LATIN_RE.findall(value))
    if hi < max(4, int(len(value) * 0.2)):
        return value
    raw = bytes(ord(ch) & 0xFF for ch in value)
    decoded = raw.decode("cp1256", errors="ignore")
    return decoded if ARABIC_RE.search(decoded) else value


def decode_bytes(b: bytes | bytearray | memoryview) -> str:
    u8 = bytes(b)
    zero_count = sum(1 for i in range(1, len(u8), 2) if u8[i] == 0)
    maybe_utf16 = len(u8) >= UTF16_MIN_BYTES and zero_count / max(1, len(u8) / 2) > UTF16_NULL_RATIO

    if maybe_utf16:
        with suppress(UnicodeDecodeError):
            return u8.decode("utf-16le")

    with suppress(UnicodeDecodeError):
        return u8.decode("cp1256")
    with suppress(UnicodeDecodeError):
        return u8.decode("utf-8")
    return ""


def decode_value(v: object) -> str:
    if isinstance(v, str):
        s = v
    elif v is None:
        return ""
    elif isinstance(v, (bytes, bytearray, memoryview)):
        s = decode_bytes(v)
    else:
        s = str(v)

    s = fix_arabic_mojibake(s)
    s = s.replace("\x00", "")
    return s.replace("ک", "ـ")


def looks_like_html(text: str) -> bool:
    return bool(LOOKS_LIKE_HTML_RE.search(text))


def sanitize_html_for_xhtml(html: str) -> str:
    return re.sub(VOID_TAG_RE, r"<\1\2 />", html)


def to_int(v: object) -> int | None:
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*[0-9\u0660-\u0669\u06F0-\u06F9]+\s*", v):
        return int(digits_to_ascii(v))
    return None


def split_plain_text(raw: object) -> list[str]:
    text = str(raw or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(
        r"بسم الله الرحمن الرحيم\s+(?=سورة|تفسير\s+سورة)", "بسم الله الرحمن الرحيم\n", text
    )
    text = re.sub(r"(?<!^)(\s+)(?=تفسير\s+سورة\s+)", "\n", text)
    if not text:
        return []

    out: list[str] = []
    for line in [line.strip() for line in re.split(r"\n+", text) if line.strip()]:
        if len(line) < LONG_LINE_LEN:
            out.append(line)
            continue
        parts = [p.strip() for p in re.split(NUMBERED_SPLIT_RE, line) if p.strip()]
        out.extend(parts if len(parts) >= MIN_SPLIT_PARTS else [line])
    return out


def to_html_paragraphs(text: object) -> list[str]:
    raw = decode_value(text).replace("\x00", "").strip()
    if not raw:
        return []
    if looks_like_html(raw):
        return [raw]
    parts = split_plain_text(raw)
    if not parts:
        return [f"<p>{escape_xml(raw)}</p>"]
    return [f"<p>{escape_xml(p)}</p>" for p in parts]


def is_heading_text(text: str) -> bool:
    return bool(re.match(r"^(?:تفسير\s+سورة|سورة)\s+", text))


def strip_tags_and_ws(html: object) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", str(html))).strip()


def get_table_header(db: AccessParser, name: str):
    t = db.get_table(name)
    return getattr(t, "table_header", None) if t else None


def get_col_names(db: AccessParser, name: str) -> list[str]:
    hdr = get_table_header(db, name)
    return (
        [c.col_name_str for c in getattr(hdr, "column_names", []) if getattr(c, "col_name_str", "")]
        if hdr
        else []
    )


def get_row_count(db: AccessParser, name: str) -> int:
    hdr = get_table_header(db, name)
    return int(getattr(hdr, "number_of_rows", 0) or 0) if hdr else 0


def pick_main_content_table(db: AccessParser, table_names: list[str]) -> str:
    b_tables = [t for t in table_names if t.lower().startswith("b")]
    return max(b_tables, key=lambda t: get_row_count(db, t)) if b_tables else ""


def pick_main_toc_table(db: AccessParser, table_names: list[str], content_table: str) -> str:
    if content_table and content_table[0].lower() == "b":
        want = "t" + content_table[1:]
        if want in table_names:
            return want
    t_tables = [t for t in table_names if t.lower().startswith("t")]
    return max(t_tables, key=lambda t: get_row_count(db, t)) if t_tables else ""


def extract_metadata(
    db: AccessParser, table_names: list[str], fallback_name: str
) -> tuple[str, str, str]:
    title = ""
    author = ""
    card = ""

    meta = "Main" if "Main" in table_names else ("main" if "main" in table_names else "")
    if meta:
        main = db.parse_table(meta)
        keys = list(main.keys())

        def pick(cands: list[str]) -> str:
            key = next((k for k in keys if k.lower() in cands), "") or next(
                (k for k in keys if any(c in k.lower() for c in cands)), ""
            )
            return decode_value((main.get(key) or [""])[0]).strip() if key else ""

        title = pick(["title", "book", "bk", "name"])
        author = pick(["author", "auth"])
        card = pick(["betaka", "card", "about"])

    if not card:
        for t in table_names:
            if any("betaka" in c.lower() for c in get_col_names(db, t)):
                rows = db.parse_table(t)
                key = next((k for k in rows if "betaka" in k.lower()), "")
                card = decode_value((rows.get(key) or [""])[0]).strip() if key else ""
                break

    if not title:
        title = re.sub(r"\.(bok|mdb|accdb)$", "", fallback_name, flags=re.IGNORECASE)

    card_html = sanitize_html_for_xhtml("".join(to_html_paragraphs(card))) if card else ""
    author_line = f"<p>المؤلف: {escape_xml(author)}</p>" if author else ""
    about = f"<div>\n<h1>{escape_xml(title)}</h1>\n{author_line}\n{card_html}\n</div>"
    return title.strip(), author.strip(), about


def pick_page_col(content_table: dict[str, list[object]], cols: list[str]) -> str | None:
    page_col = "page" if "page" in cols else next((c for c in cols if "page" in c.lower()), "")
    if not page_col:
        return None
    if "hno" not in cols:
        return page_col

    hno_vals = [to_int(v) for v in (content_table.get("hno") or [])[:PREVIEW_ROWS]]
    hno_vals = [v for v in hno_vals if isinstance(v, int)]
    max_hno = max(hno_vals) if hno_vals else 0

    page_vals = [to_int(v) for v in (content_table.get(page_col) or [])[:PREVIEW_ROWS]]
    page_vals = [v for v in page_vals if isinstance(v, int)]
    max_page = max(page_vals) if page_vals else 0

    return "hno" if max_hno > max(50, max_page + 50) else page_col


def parse_raw_toc(
    toc_table: dict[str, list[object]], *, text_col: str, start_col: str, level_col: str | None
) -> list[dict[str, Any]] | None:
    if not text_col or not start_col:
        return None

    n = max((len(v) for v in toc_table.values()), default=0)
    texts = toc_table.get(text_col) or []
    starts = toc_table.get(start_col) or []
    levels = (toc_table.get(level_col) or []) if level_col else []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(n):
        text = decode_value(texts[i] if i < len(texts) else "").strip()
        start = to_int(starts[i] if i < len(starts) else None)
        level = to_int(levels[i] if i < len(levels) else None) if level_col else None
        if not text or start is None:
            continue
        if re.match(r"^الجزء\s+", text):
            continue
        key = f"{start}|{level or ''}|{text}"
        if key in seen:
            continue
        seen.add(key)
        items.append({"start": start, "text": text, "level": level})

    levels_only = [it["level"] for it in items if isinstance(it.get("level"), int)]
    if levels_only:
        mn = min(levels_only)
        shift = 1 - mn if mn <= 0 else (1 - mn if mn > 1 else 0)
        if shift:
            for it in items:
                if isinstance(it.get("level"), int):
                    it["level"] = int(it["level"]) + shift

    return items or None


def nest_by_level(items: list[dict[str, Any]], make_entry):
    root: list[Any] = []
    stack: list[tuple[int, list[Any]]] = [(0, root)]
    for it in items:
        lv = it.get("level")
        level = int(lv) if isinstance(lv, int) and lv > 0 else 1
        while len(stack) > 1 and stack[-1][0] >= level:
            stack.pop()
        children: list[Any] = []
        stack[-1][1].append((make_entry(it), children))
        stack.append((level, children))
    return root


def _make_chunks(raw: str, *, split_numbered: bool) -> list[list[str]]:
    if not split_numbered or looks_like_html(raw):
        paras = to_html_paragraphs(raw)
        return [paras] if paras else []

    parts_txt = split_plain_text(raw)
    chunks_txt: list[list[str]] = []
    cur: list[str] = []
    for t in (p.strip() for p in parts_txt):
        if not t:
            continue
        if cur and (is_heading_text(t) or bool(NUMBERED_LINE_RE.search(t))):
            chunks_txt.append(cur)
            cur = [t]
        else:
            cur.append(t)
    if cur:
        chunks_txt.append(cur)

    return [[f"<p>{escape_xml(p)}</p>" for p in lst] for lst in chunks_txt if lst]


def _anchor_chunk_index(chunks: list[list[str]]) -> int:
    for idx, chunk in enumerate(chunks):
        first = strip_tags_and_ws(chunk[0] if chunk else "")
        if is_heading_text(first):
            return idx
    return 0


def _footer(*, part_display: str, page: int | None) -> str:
    return " - ".join(
        [
            x
            for x in [
                f"الجزء: {part_display}" if part_display else "",
                f"الصفحة: {page}" if page else "",
            ]
            if x
        ]
    )


def build_pages(
    content_table: dict[str, list[object]],
    cols: ContentCols,
    *,
    toc_starts: set[int] | None,
    split_numbered: bool,
) -> tuple[list[dict[str, Any]], dict[int, int], dict[int, str]]:
    n = max((len(v) for v in content_table.values()), default=0)
    texts = content_table.get(cols.text) or []
    ids = (content_table.get(cols.id) or []) if cols.id else []
    pages_col = (content_table.get(cols.page) or []) if cols.page else []
    parts = (content_table.get(cols.part) or []) if cols.part else []

    pages: list[dict[str, Any]] = []
    id_to_page_number: dict[int, int] = {}
    id_to_snippet: dict[int, str] = {}

    for i in range(n):
        raw = decode_value(texts[i] if i < len(texts) else "").replace("\x00", "").strip()
        if not raw:
            continue

        idv = to_int(ids[i] if i < len(ids) else None) if cols.id else None
        pv = to_int(pages_col[i] if i < len(pages_col) else None) if cols.page else None
        part_raw = parts[i] if i < len(parts) else None
        partv = to_int(part_raw) if cols.part else None
        part_text = (
            decode_value(part_raw).replace("\x00", "").strip()
            if cols.part and partv is None
            else ""
        )
        part_display = str(partv) if partv is not None else (part_text or "")

        chunks = _make_chunks(raw, split_numbered=split_numbered)
        if not chunks:
            continue

        is_toc_start = bool(toc_starts and idv is not None and idv in toc_starts)
        anchor_chunk_index = _anchor_chunk_index(chunks) if is_toc_start else 0
        footer = _footer(part_display=part_display, page=pv)

        for chunk_index, paras in enumerate(chunks):
            out: list[str] = []
            if is_toc_start and chunk_index == anchor_chunk_index:
                out.append(f'<a id="toc_{idv}"></a>')
            out.extend(paras)
            body = f"<div>{''.join(out)}</div>"
            text_html = f'{body}<div class="text-center">{footer}</div>' if footer else body
            page_number = len(pages) + 1
            pages.append(
                {
                    "page_number": page_number,
                    "page": pv or 0,
                    "part": partv,
                    "text_html": sanitize_html_for_xhtml(text_html),
                }
            )

            if idv is not None and (not is_toc_start or chunk_index == anchor_chunk_index):
                id_to_page_number[idv] = page_number

        if idv is not None and idv not in id_to_snippet:
            flat = [p for chunk in chunks for p in chunk]
            lines = [strip_tags_and_ws(p) for p in flat[:SNIPPET_LINES]]
            id_to_snippet[idv] = "\n".join(lines).strip()

    return pages, id_to_page_number, id_to_snippet


def auto_toc_from_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in pages:
        m = re.search(r"<p[^>]*>([\s\S]*?)</p>", str(page.get("text_html") or ""), re.IGNORECASE)
        if not m:
            continue
        t = strip_tags_and_ws(m.group(1))
        if not t or len(t) > MAX_AUTO_TOC_TITLE_LEN:
            continue
        if is_heading_text(t) and t not in seen:
            seen.add(t)
            items.append({"page": int(page["page_number"]), "text": t, "anchor": ""})

    return items or None


def map_toc(
    raw_toc: list[dict[str, Any]] | None,
    id_to_page_number: dict[int, int],
    id_to_snippet: dict[int, str],
):
    if not raw_toc:
        return None

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in raw_toc:
        start = int(entry["start"])
        page_number = id_to_page_number.get(start) or (1 if start == 0 else None)
        if not page_number:
            continue

        text = str(entry["text"])
        snippet = id_to_snippet.get(start, "")
        if text.startswith("سورة "):
            alt = f"تفسير {text}"
            if alt in snippet:
                text = alt

        level = entry.get("level")
        key = f"{page_number}|{level or ''}|{text}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "text": text,
                "page": page_number,
                "anchor": "" if start == 0 else f"toc_{start}",
                "level": level,
            }
        )

    if not items:
        return None

    if not any(isinstance(it.get("level"), int) for it in items):
        items.sort(key=lambda x: int(x["page"]))
        return [{k: v for k, v in it.items() if k != "level"} for it in items]

    return nest_by_level(
        items, lambda it: {"text": it["text"], "page": it["page"], "anchor": it["anchor"]}
    )


BASE_CSS = "*{direction: rtl}\nbody{line-height:1.7;margin:1.5rem;color:#1f1f1f}\n.text-center,h1,h2,h3{text-align:center}"


def render_page(title: str, text_html: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ar" dir="rtl">
  <head>
    <meta charset="utf-8" />
    <title>{escape_xml(title)}</title>
    <link rel="stylesheet" href="../styles.css" />
  </head>
  <body>
    {text_html}
  </body>
</html>
"""


def render_nav_items(toc: list[Any], page_map: dict[int, str]) -> str:
    def render_list(items: list[Any]) -> str:
        return f"<ol>{''.join(render_item(it) for it in items)}</ol>" if items else ""

    def render_item(item: Any) -> str:
        if isinstance(item, tuple) and len(item) == PAIR_LEN:
            entry, children = item
            href = f"{page_map[int(entry['page'])]}{('#' + entry['anchor']) if entry.get('anchor') else ''}"
            return (
                f'<li><a href="{href}">{escape_xml(entry["text"])}</a>{render_list(children)}</li>'
            )
        href = (
            f"{page_map[int(item['page'])]}{('#' + item['anchor']) if item.get('anchor') else ''}"
        )
        return f'<li><a href="{href}">{escape_xml(item["text"])}</a></li>'

    return render_list(toc)


def render_ncx_items(toc: list[Any], page_map: dict[int, str]) -> str:
    nav_index = 0

    def render_item(item: Any) -> str:
        nonlocal nav_index
        item_id = f"nav_{nav_index}"
        nav_index += 1

        if isinstance(item, tuple) and len(item) == PAIR_LEN:
            entry, children = item
            href = f"{page_map[int(entry['page'])]}{('#' + entry['anchor']) if entry.get('anchor') else ''}"
            kids = "".join(render_item(c) for c in children)
            return f'<navPoint id="{item_id}"><navLabel><text>{escape_xml(entry["text"])}</text></navLabel><content src="{href}"/>{kids}</navPoint>'

        href = (
            f"{page_map[int(item['page'])]}{('#' + item['anchor']) if item.get('anchor') else ''}"
        )
        return f'<navPoint id="{item_id}"><navLabel><text>{escape_xml(item["text"])}</text></navLabel><content src="{href}"/></navPoint>'

    return "".join(render_item(it) for it in toc)


def render_nav(title: str, toc_tree: list[Any], page_map: dict[int, str]) -> str:
    toc_html = render_nav_items(toc_tree, page_map) if toc_tree else ""
    info_link = '<li><a href="info.xhtml">بطاقة الكتاب</a></li>'
    nav_link = '<li><a href="nav.xhtml">فهرس الموضوعات</a></li>'
    nav_items = (
        toc_html.replace("<ol>", f"<ol>{info_link}{nav_link}", 1)
        if toc_html.startswith("<ol>")
        else f"<ol>{info_link}{nav_link}</ol>"
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ar" dir="rtl">
  <head>
    <meta charset="utf-8" />
    <title>{escape_xml(title)}</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>فهرس الموضوعات</h1>
      {nav_items}
    </nav>
  </body>
  </html>
"""


def render_ncx(title: str, toc_tree: list[Any], page_map: dict[int, str], *, uid: str) -> str:
    ncx_items = render_ncx_items(toc_tree, page_map) if toc_tree else ""
    return f'''<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta content="{escape_xml(uid)}" name="dtb:uid"/>
    <meta content="0" name="dtb:depth"/>
    <meta content="0" name="dtb:totalPageCount"/>
    <meta content="0" name="dtb:maxPageNumber"/>
  </head>
  <docTitle>
    <text>{escape_xml(title)}</text>
  </docTitle>
  <navMap>
    <navPoint id="info">
      <navLabel><text>بطاقة الكتاب</text></navLabel>
      <content src="info.xhtml"/>
    </navPoint>
    <navPoint id="nav">
      <navLabel><text>فهرس الموضوعات</text></navLabel>
      <content src="nav.xhtml"/>
    </navPoint>
    {ncx_items}
  </navMap>
</ncx>
'''


def render_opf(  # noqa: PLR0913
    title: str,
    author: str,
    manifest_items: str,
    spine_items: str,
    *,
    include_toc_page: bool,
    modified: str,
) -> str:
    identifier = "urn:shamela_bok:0"
    author_xml = f"<dc:creator>{escape_xml(author)}</dc:creator>" if author else ""
    include_toc = '<itemref idref="nav" />' if include_toc_page else ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{escape_xml(identifier)}</dc:identifier>
    <dc:title>{escape_xml(title)}</dc:title>
    {author_xml}
    <dc:publisher>Shamela (.bok)</dc:publisher>
    <dc:language>ar</dc:language>
    <meta property="dcterms:modified">{escape_xml(modified)}</meta>
  </metadata>
  <manifest>
    <item id="info" href="info.xhtml" media-type="application/xhtml+xml" />
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
    <item id="css" href="styles.css" media-type="text/css" />
    {manifest_items}
  </manifest>
  <spine toc="ncx" page-progression-direction="rtl">
    {include_toc}
    {spine_items}
  </spine>
</package>
"""


def write_epub(out_file: Path, book: EpubBook, *, include_toc_page: bool) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)

    sorted_pages = sorted(book.pages, key=lambda p: int(p["page_number"]))
    zfill = len(str(sorted_pages[-1]["page_number"])) + 1 if sorted_pages else 2

    page_entries: list[tuple[int, str, dict[str, Any]]] = []
    for p in sorted_pages:
        part = p.get("part")
        prefix = f"page_{int(part)}_" if isinstance(part, int) else "page_"
        file_name = f"{prefix}{int(p['page_number']):0{zfill}d}.xhtml"
        page_entries.append((int(p["page_number"]), file_name, p))

    page_map = {page_number: f"text/{file_name}" for page_number, file_name, _ in page_entries}

    modified = datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    uid = str(uuid.uuid4())

    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        z.writestr(mimetype, "application/epub+zip")

        z.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
""",
        )

        z.writestr("OEBPS/styles.css", BASE_CSS)

        for _, file_name, page in page_entries:
            z.writestr(f"OEBPS/text/{file_name}", render_page(book.title, str(page["text_html"])))

        z.writestr(
            "OEBPS/info.xhtml",
            f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ar" dir="rtl">
  <head>
    <meta charset="utf-8" />
    <title>بطاقة الكتاب</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    {sanitize_html_for_xhtml(book.about)}
  </body>
</html>
""",
        )

        z.writestr("OEBPS/nav.xhtml", render_nav(book.title, book.toc_tree, page_map))
        z.writestr("OEBPS/toc.ncx", render_ncx(book.title, book.toc_tree, page_map, uid=uid))

        manifest_items = "".join(
            f'<item id="p{page_number}" href="text/{file_name}" media-type="application/xhtml+xml" />'
            for page_number, file_name, _ in page_entries
        )
        spine_items = "".join(
            f'<itemref idref="p{page_number}" />' for page_number, _, _ in page_entries
        )
        z.writestr(
            "OEBPS/content.opf",
            render_opf(
                book.title,
                book.author,
                manifest_items,
                spine_items,
                include_toc_page=include_toc_page,
                modified=modified,
            ),
        )


def bok_to_epub(
    input_bok: Path,
    out_epub: Path,
    *,
    include_toc_page: bool = False,
    split_numbered: bool = False,
) -> None:
    db = AccessParser(input_bok)
    table_names = sorted([t for t in db.catalog if t != "MSysObjects"])

    content_table_name = pick_main_content_table(db, table_names)
    if not content_table_name:
        raise ValueError("could not find a content table")
    toc_table_name = pick_main_toc_table(db, table_names, content_table_name)

    title, author, about = extract_metadata(db, table_names, input_bok.name)

    content_cols = get_col_names(db, content_table_name)
    content_table = db.parse_table(content_table_name)

    text_col = (
        "nass"
        if "nass" in content_cols
        else next(
            (
                c
                for c in content_cols
                if any(isinstance(v, str) for v in (content_table.get(c) or [])[:50])
            ),
            "",
        )
    )
    if not text_col:
        raise ValueError("حدد جدول المحتوى وعمود النص")

    cols = ContentCols(
        text=text_col,
        id="id" if "id" in content_cols else None,
        page=pick_page_col(content_table, content_cols),
        part="part"
        if "part" in content_cols
        else next((c for c in content_cols if c.lower() == "part" or "part" in c.lower()), None),
    )

    raw_toc = None
    if toc_table_name:
        toc_cols = get_col_names(db, toc_table_name)
        toc_table = db.parse_table(toc_table_name)
        toc_text_col = (
            "tit"
            if "tit" in toc_cols
            else next(
                (
                    c
                    for c in toc_cols
                    if any(isinstance(v, str) for v in (toc_table.get(c) or [])[:50])
                ),
                "",
            )
        )
        toc_start_col = "id" if "id" in toc_cols else ("page" if "page" in toc_cols else "")
        toc_level_col = "lvl" if "lvl" in toc_cols else ("level" if "level" in toc_cols else None)
        raw_toc = parse_raw_toc(
            toc_table, text_col=toc_text_col, start_col=toc_start_col, level_col=toc_level_col
        )

    toc_starts = {int(it["start"]) for it in raw_toc} if raw_toc else None
    pages, id_to_page_number, id_to_snippet = build_pages(
        content_table,
        cols,
        toc_starts=toc_starts,
        split_numbered=split_numbered,
    )

    toc_tree = map_toc(raw_toc, id_to_page_number, id_to_snippet) if raw_toc else None
    if not toc_tree:
        toc_tree = auto_toc_from_pages(pages)
    if not toc_tree:
        toc_tree = [
            {"page": int(p["page_number"]), "text": f"صفحة {p.get('page')}", "anchor": ""}
            for p in pages
        ]

    write_epub(
        out_epub,
        EpubBook(title=title, author=author, about=about, pages=pages, toc_tree=toc_tree),
        include_toc_page=include_toc_page,
    )
