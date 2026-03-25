import posixpath


def escape_xml(value: object) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def normalize_lang(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def resolve_relative_zip_path(base_dir: str, href: str) -> str:
    return posixpath.normpath(f"/{base_dir}/{href}").lstrip("/")


def relative_zip_path(from_dir: str, target_path: str) -> str:
    if not target_path:
        return ""
    relative = posixpath.relpath(target_path, start=from_dir or ".")
    return target_path if relative == "." else relative
