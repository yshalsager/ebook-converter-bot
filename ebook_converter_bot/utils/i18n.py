from gettext import GNUTranslations, NullTranslations, translation

from ebook_converter_bot import LANGUAGES, LOCALE_PATH

TRANSLATIONS: dict[str, GNUTranslations | NullTranslations] = {
    lang: translation(
        "ebook_converter_bot", localedir=LOCALE_PATH, languages=[lang], fallback=True
    )
    for lang in LANGUAGES
}


def translate(string: str, lang: str | None) -> str:
    if not lang:
        lang = "en"
    translated = TRANSLATIONS[lang].gettext(string)
    while "  " in translated:
        translated = translated.replace("  ", " ")
    return translated
