# E-Book Converter Bot

[![Telegram Badge](https://img.shields.io/badge/Telegram-Use%20Now!-2CA5E0?style=flat&labelColor=2CA5E0&logo=Telegram&logoColor=white&link=https://t.me/ebook_converter_bot)](https://t.me/ebook_converter_bot)

[![Open Source Love](https://badges.frapsoft.com/os/v1/open-source.png?v=103)](https://github.com/ellerbrock/open-source-badges/)
[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/yshalsager/ebook-converter-bot/master.svg)](https://results.pre-commit.ci/latest/github/yshalsager/ebook-converter-bot/master)


[![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?style=flat&labelColor=00457C&logo=PayPal&logoColor=white&link=https://www.paypal.me/yshalsager)](https://www.paypal.me/yshalsager)
[![Patreon](https://img.shields.io/badge/Patreon-Support-F96854?style=flat&labelColor=F96854&logo=Patreon&logoColor=white&link=https://www.patreon.com/XiaomiFirmwareUpdater)](https://www.patreon.com/XiaomiFirmwareUpdater)
[![Liberapay](https://img.shields.io/badge/Liberapay-Support-F6C915?style=flat&labelColor=F6C915&logo=Liberapay&logoColor=white&link=https://liberapay.com/yshalsager)](https://liberapay.com/yshalsager)

A bot that converts e-books to various formats, powered by [calibre](https://calibre-ebook.com/), [Pandoc](https://pandoc.org/), and [Antiword](https://www.winfield.demon.nl/)!
It currently supports 49 input formats and 29 output formats.

You can start using it or adding it to your group [here on Telegram](https://t.me/ebook_converter_bot).

## About the code:

This project is a modular bot, made using Python 3 and the following:

- [Telethon Library](https://github.com/LonamiWebs/Telethon/)
- [Calibre](https://calibre-ebook.com/)
- [Pandoc](https://pandoc.org/)
- [Antiword](https://www.winfield.demon.nl/)

## Bot features:

This bot aims to provide an easy way for telegram users to convert e-books from and to different formats.

It supports converting from the following formats:

```python
['azw', 'azw3', 'azw4', 'azw8', 'adoc', 'asciidoc', 'bok', 'cb7', 'cbc', 'cbr',
 'cbz', 'chm', 'djvu', 'doc', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz',
 'kepub', 'kfx', 'kfx-zip', 'kpf', 'lit', 'lrf', 'md', 'mediawiki', 'mobi', 'odt',
 'opf', 'org', 'pdb', 'pdf', 'pml', 'prc', 'rb', 'rst', 'rtf', 'snb', 't2t',
 'tcr', 'tex', 'textile', 'tsv', 'txt', 'txtz', 'typ', 'typst']
```

To the following formats:

```python
['azw3', 'adoc', 'docx', 'epub', 'fb2', 'html', 'htmlz', 'kepub', 'kfx', 'lit',
 'lrf', 'md', 'mobi', 'oeb', 'org', 'pdb', 'pdf', 'pmlz', 'rb', 'rst', 'rtf',
 'snb', 'tcr', 'tex', 'txt', 'txtz', 'typ', 'typst', 'zip']
```

Some more features of the bot:

- Force book direction to be RTL
- Multilingual support, you can contribute and add your own languages if you want :).
- Flatten book's table of contents.
- Convert Shamela old `.bok` files by first generating an EPUB in Python then using the existing calibre pipeline for other outputs.
- Convert legacy Word `.doc` files by extracting text with Antiword, then using the existing Calibre or Pandoc pipeline.
- Interactive conversion options before selecting output format.
- Per-user conversion option defaults are remembered automatically.
- Optional Pandoc backend for supported document routes, with Calibre as the default when both can convert the same route.
- Markdown-family, HTML, reStructuredText, AsciiDoc, Org, LaTeX, Typst, and plain-text document routes through Pandoc.
- Global output options: cover compression, smart punctuation, text justification, line height, and paragraph spacing cleanup.
- DOCX options: page size and generated TOC toggle.
- EPUB output options: version selection, inline TOC, and background removal.
- PDF options: paper size, page numbers, cover-page generation, chapter page breaks, and Arabic font selection.
- KFX options: PDOC/EBOK type and pages mode.
- EPUB input preprocessing options: fix EPUB metadata/spine issues, flatten TOC, and standardize footnotes.
- EPUB-to-EPUB volume splitting with per-volume output processing (up to 35 split files).
- Admin stats track users, recent attempts, success/failure rates, active users, and top conversion pairs.
- Admin broadcasts retry flood waits per recipient, remove permanently unreachable chats, and support `active_within` and
  `username_only` filters.

## Usage

- Forward any supported file to the bot and choose the required format to convert to, and in few seconds the bot will
  reply you with the converted file.
- The bot works in groups too. Reply with `/convert` to any file then do the same steps as in private.
- You can change the preferences of the bot such as language using `/settings` or `/preferences` commands.

Admin-only commands:

- `/stats` shows user and conversion activity statistics.
- `/broadcast` sends the replied message to all stored chats. You can add optional filters under the command:
  ```text
  /broadcast
  active_within 30
  username_only yes
  ```
- `/update` updates the bot from a GitHub source archive without requiring git in the runtime container.
- `/restart` restarts the bot.

## Before setting up the bot

- Copy `config.json.example` file to `config.json` and fill the required information:
  ```json
  {
    "tg_bot_token": "11111111:xxxxxxxxxxxxxxxxxx",
    "tg_bot_id": 111111111,
    "api_key": 1121221,
    "api_hash": "xxxxxxxxxxxxxxxxxxxx",
    "tg_bot_admins": [
      2222222
    ]
  }
  ```
- Compile the translation files using the following command:
  ```bash
  mise run i18n_compile
  ```

## Setting up the bot

Before all, clone this repository.

### Using Docker

- Simply, run the following command:

```bash
docker compose up --build -d
```

The Docker setup uses uv for Python dependencies, installs runtime dependencies into `/opt/venv`, and runs the bot from
the repository mounted at `/app`.

For KFX conversion on recent Docker versions, the compose file uses Docker's targeted seccomp workaround for Wine:

```yaml
security_opt:
  - seccomp=/etc/docker/seccomp-profile-v0.2.1.json
```

Download that profile on the host before starting the container, or remove this setting if you do not need KFX/Wine
conversion.

### Without Docker [NOT RECOMMENDED]

#### Python dependencies

It requires Python 3.14 and uv.

Clone the repository and run:

```bash
uv sync --frozen
```

#### Database

The bot uses SQLite through SQLAlchemy. Alembic runs database migrations automatically on startup.

#### Other requirements

You can go through the Dockerfile to see how the bot requirements are being installed.

- The conversion process is done by utilizing [Calibre](https://calibre-ebook.com/) and its ebook-convert, so make sure
  you have it installed.
- Pandoc is required for Pandoc-backed document routes such as Markdown, HTML, reStructuredText, AsciiDoc, Org, LaTeX,
  Typst, and some DOCX/EPUB/TXT conversions.
- Antiword is required for legacy Word `.doc` input files. The bot extracts `.doc` text first, then converts the
  extracted text to the requested output format.
- To convert from and to KFX, you need to install [KFX Input](https://www.mobileread.com/forums/showthread.php?t=291290)
  and [KFX Output](https://www.mobileread.com/forums/showthread.php?t=272407) plugins in calibre, this can be done from
  the command line by using the following commands:
  ```bash
  # KFX Input
  wget https://plugins.calibre-ebook.com/291290.zip 
  calibre-customize -a 291290.zip
  # KFX Output
  wget https://plugins.calibre-ebook.com/272407.zip
  calibre-customize -a 272407.zip
  ```
- Also, KFX Output plugin requires [Kindle Previewer 3](https://kdp.amazon.com/en_US/help/topic/G202131170), which can
  run on linux under [Wine](https://appdb.winehq.org/objectManager.php?sClass=application&iId=18012).

#### Running the bot

If you finally managed to get all pieces in its place without using docker, run the bot using:

```bash
uv run -m ebook_converter_bot
```

### Internationalization (i18n)

The bot uses gettext for internationalization and mise tasks for running i18n commands easily.

- First, generate .pot template using `mise run i18n_generate_messages`.
- Update the current translation files using `mise run i18n_merge`, then edit the translation strings.
- Compile the translation files using `mise run i18n_compile`.

To add a new language to the bot, run the following command (change 'ar' to your language code) then edit the new
language file with translation and compile.

```bash
mise run i18n_init_lang -- ar
```

## `.bok` Notes

Shamela old `.bok` files are first converted to an intermediate EPUB in pure Python (using `access-parser`), then (if the requested output isn't EPUB) calibre is used to convert that EPUB to the requested format.

For local debugging, there's also a small CLI wrapper:

```bash
uv run scripts/bok_to_epub.py path/to/book.bok
```
