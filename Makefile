i18n-generate-messages:
		find "ebook_converter_bot/modules/" -iname "*.py" | xargs xgettext -L Python -c -o ebook_converter_bot/data/locales/ebook_converter_bot.pot
i18n-init-lang:
		mkdir -p ebook_converter_bot/data/locales/$(LANG)/LC_MESSAGES/ && cp ebook_converter_bot/data/locales/ebook_converter_bot.pot ebook_converter_bot/data/locales/$(LANG)/LC_MESSAGES/ebook_converter_bot.po
i18n-merge:
		 find ebook_converter_bot/data/locales -name "*.po" | xargs -I {} msgmerge --update {} ebook_converter_bot/data/locales/ebook_converter_bot.pot
i18n-compile:
		find ebook_converter_bot/data/locales -name "*.po" | xargs -I {} echo msgfmt -o {} {} | sed 's/po/mo/1' | bash
