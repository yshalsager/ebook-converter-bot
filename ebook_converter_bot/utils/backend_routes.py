"""Format capabilities shared by the backend chooser and conversion dispatch."""

ANYDOC_INPUT_TYPES = {"doc", "docm", "odp", "ods", "ppt", "xls", "xlsm"}
PANDOC_SHARED_INPUT_TYPES = {
    *ANYDOC_INPUT_TYPES,
    "docx",
    "epub",
    "fb2",
    "htm",
    "html",
    "md",
    "odt",
    "rtf",
    "txt",
    "xhtml",
}
PANDOC_ONLY_INPUT_TYPES = {
    "adoc",
    "asciidoc",
    "csv",
    "ipynb",
    "mediawiki",
    "org",
    "pptx",
    "rst",
    "t2t",
    "tex",
    "textile",
    "tsv",
    "typ",
    "typst",
    "xlsx",
}
SHARED_BACKEND_OUTPUT_TYPES = {"docx", "epub", "txt"}
PANDOC_ONLY_OUTPUT_TYPES = {
    "adoc",
    "html",
    "md",
    "odt",
    "org",
    "pptx",
    "rst",
    "tex",
    "typ",
    "typst",
}
CALIBRE_OUTPUT_TYPES = [
    "azw3",
    "docx",
    "epub",
    "fb2",
    "htmlz",
    "kepub",
    "kfx",
    "lit",
    "lrf",
    "mobi",
    "oeb",
    "pdb",
    "pdf",
    "pmlz",
    "rb",
    "rtf",
    "snb",
    "tcr",
    "txt",
    "txtz",
    "zip",
]
BOKO_INPUT_TYPES = {"epub", "azw3", "mobi", "azw", "kfx"}
BOKO_OUTPUT_TYPES = {"epub", "azw3", "kfx", "md"}
KFX_INPUT_TYPES = {"azw8", "kfx", "kfx-zip"}
KFX_OUTPUT_INPUT_TYPES = {"epub", "opf", "mobi", "doc", "docx", "kpf", "kfx-zip"}
FORMAT_ALIASES = {"asciidoc": "adoc", "htm": "html", "xhtml": "html", "typst": "typ"}


def prepared_input_type(input_type: str, output_type: str) -> str:
    if input_type in ANYDOC_INPUT_TYPES:
        return "md"
    if input_type == "bok" or input_type in KFX_INPUT_TYPES:
        return "epub"
    if input_type == "pdf":
        return "epub" if output_type == "kfx" else "htmlz"
    return input_type


def backend_choices(input_type: str, output_type: str) -> list[str]:
    prepared_type = prepared_input_type(input_type, output_type)
    same_format = FORMAT_ALIASES.get(input_type, input_type) == FORMAT_ALIASES.get(
        output_type, output_type
    )
    if same_format and input_type != "epub":
        return []

    choices = []
    if (
        prepared_type not in PANDOC_ONLY_INPUT_TYPES
        and output_type in CALIBRE_OUTPUT_TYPES
        and (output_type != "kfx" or prepared_type in KFX_OUTPUT_INPUT_TYPES | {"md"})
    ):
        choices.append("calibre")
    if (
        prepared_type in PANDOC_SHARED_INPUT_TYPES | PANDOC_ONLY_INPUT_TYPES
        and output_type in SHARED_BACKEND_OUTPUT_TYPES | PANDOC_ONLY_OUTPUT_TYPES
        and (
            FORMAT_ALIASES.get(prepared_type, prepared_type)
            != FORMAT_ALIASES.get(output_type, output_type)
            or (input_type in ANYDOC_INPUT_TYPES and output_type == "md")
        )
    ):
        choices.append("pandoc")
    if (
        output_type in BOKO_OUTPUT_TYPES
        and not same_format
        and (
            input_type in BOKO_INPUT_TYPES
            or (input_type == "bok" and output_type != "epub")
            or (input_type == "pdf" and output_type == "kfx")
        )
    ):
        choices.append("boko")
    if output_type == "kfx" and prepared_type not in PANDOC_ONLY_INPUT_TYPES | KFX_INPUT_TYPES | {
        "kpf"
    }:
        choices.append("kfxgen")
    return choices


def resolve_backend(input_type: str, output_type: str, preferred: str) -> str:
    choices = backend_choices(input_type, output_type)
    return preferred if preferred in choices else next(iter(choices), "calibre")
