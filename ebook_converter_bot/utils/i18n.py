from gettext import translation, GNUTranslations
from typing import Dict

from ebook_converter_bot import LOCALE_PATH, LANGUAGES

TRANSLATIONS: Dict[str, GNUTranslations] = {
    lang: translation(
        'ebook_converter_bot', localedir=LOCALE_PATH, languages=[lang], fallback=True)
    for lang in LANGUAGES
}


def translate(string, lang) -> str:
    if not lang:
        lang = 'en'
    translated = TRANSLATIONS[lang].gettext(string)
    while '  ' in translated:
        translated = translated.replace('  ', ' ')
    return translated
