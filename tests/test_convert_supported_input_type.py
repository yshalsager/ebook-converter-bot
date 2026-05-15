from ebook_converter_bot.utils.convert import Converter


def test_is_supported_input_type_handles_missing_name() -> None:
    assert Converter().is_supported_input_type(None) is False


def test_is_supported_input_type_is_case_insensitive() -> None:
    assert Converter().is_supported_input_type("Book.EPUB") is True


def test_shared_pandoc_inputs_expose_markdown_output_but_non_pandoc_inputs_do_not() -> None:
    assert "md" in Converter.get_supported_output_types_for_input("docx")
    assert "md" in Converter.get_supported_output_types_for_input("epub")
    assert "md" not in Converter.get_supported_output_types_for_input("mobi")


def test_shared_pandoc_inputs_do_not_expose_same_format_output() -> None:
    assert "md" not in Converter.get_supported_output_types_for_input("md")
    assert "html" not in Converter.get_supported_output_types_for_input("html")
    assert "typ" not in Converter.get_supported_output_types_for_input("typst")
    assert "typst" not in Converter.get_supported_output_types_for_input("typ")


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
