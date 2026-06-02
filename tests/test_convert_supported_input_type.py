from ebook_converter_bot.utils.convert import Converter


def test_is_supported_input_type_handles_missing_name() -> None:
    assert Converter().is_supported_input_type(None) is False


def test_is_supported_input_type_is_case_insensitive() -> None:
    assert Converter().is_supported_input_type("Book.EPUB") is True


def test_shared_pandoc_inputs_expose_markdown_output_but_non_pandoc_inputs_do_not() -> None:
    assert "md" in Converter.get_supported_output_types_for_input("doc")
    assert "md" in Converter.get_supported_output_types_for_input("docx")
    assert "md" in Converter.get_supported_output_types_for_input("epub")
    assert "md" not in Converter.get_supported_output_types_for_input("mobi")


def test_shared_pandoc_inputs_do_not_expose_same_format_output() -> None:
    assert "md" not in Converter.get_supported_output_types_for_input("md")
    assert "html" not in Converter.get_supported_output_types_for_input("html")
    assert "typ" not in Converter.get_supported_output_types_for_input("typst")
    assert "typst" not in Converter.get_supported_output_types_for_input("typ")


def test_epub_input_keeps_epub_output_for_preprocess_routes() -> None:
    assert "epub" in Converter.get_supported_output_types_for_input("epub")


def test_pandoc_capable_inputs_expose_extended_markup_outputs() -> None:
    output_types = Converter.get_supported_output_types_for_input("adoc")
    asciidoc_output_types = Converter.get_supported_output_types_for_input("asciidoc")

    assert "epub" in output_types
    assert "docx" in output_types
    assert "md" in output_types
    assert "html" in output_types
    assert "rst" in output_types
    assert "adoc" not in output_types
    assert "adoc" not in asciidoc_output_types


def test_csv_input_is_pandoc_only_like_tsv() -> None:
    output_types = Converter.get_supported_output_types_for_input("csv")

    assert Converter().is_supported_input_type("table.CSV") is True
    assert "docx" in output_types
    assert "epub" in output_types
    assert "md" in output_types
    assert "html" in output_types
    assert "azw3" not in output_types


def test_common_document_inputs_are_pandoc_only() -> None:
    for input_type in ("xlsx", "pptx", "ipynb"):
        output_types = Converter.get_supported_output_types_for_input(input_type)

        assert Converter().is_supported_input_type(f"book.{input_type.upper()}") is True
        assert "docx" in output_types
        assert "epub" in output_types
        assert "md" in output_types
        assert "html" in output_types
        assert "azw3" not in output_types


def test_pandoc_output_formats_are_exposed() -> None:
    output_types = Converter.get_supported_output_types_for_input("docx")

    assert "odt" in output_types
    assert "pptx" in output_types


def test_fb2_input_keeps_calibre_outputs_and_exposes_pandoc_outputs() -> None:
    output_types = Converter.get_supported_output_types_for_input("fb2")

    assert "azw3" in output_types
    assert "md" in output_types
    assert "odt" in output_types
    assert "pptx" in output_types
    assert "fb2" not in output_types


def test_common_calibre_aliases_are_supported() -> None:
    for input_type in ("djv", "docm"):
        assert Converter().is_supported_input_type(f"book.{input_type.upper()}") is True
        assert (
            Converter.get_supported_output_types_for_input(input_type)
            == Converter.calibre_output_types
        )


def test_html_aliases_behave_like_shared_html_input() -> None:
    for input_type in ("htm", "xhtml"):
        output_types = Converter.get_supported_output_types_for_input(input_type)

        assert Converter().is_supported_input_type(f"book.{input_type.upper()}") is True
        assert "azw3" in output_types
        assert "docx" in output_types
        assert "md" in output_types
