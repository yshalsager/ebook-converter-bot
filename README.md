# E-Book Converter Bot

[![Telegram Badge](https://img.shields.io/badge/Telegram-Use%20Now!-2CA5E0?style=flat&labelColor=2CA5E0&logo=Telegram&logoColor=white&link=https://t.me/ebook_converter_bot)](https://t.me/ebook_converter_bot)

[![Open Source Love](https://badges.frapsoft.com/os/v1/open-source.png?v=103)](https://github.com/ellerbrock/open-source-badges/)
[![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/yshalsager/ebook-converter-bot/master.svg)](https://results.pre-commit.ci/latest/github/yshalsager/ebook-converter-bot/master)


[![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?style=flat&labelColor=00457C&logo=PayPal&logoColor=white&link=https://www.paypal.me/yshalsager)](https://www.paypal.me/yshalsager)
[![Patreon](https://img.shields.io/badge/Patreon-Support-F96854?style=flat&labelColor=F96854&logo=Patreon&logoColor=white&link=https://www.patreon.com/XiaomiFirmwareUpdater)](https://www.patreon.com/XiaomiFirmwareUpdater)
[![Liberapay](https://img.shields.io/badge/Liberapay-Support-F6C915?style=flat&labelColor=F6C915&logo=Liberapay&logoColor=white&link=https://liberapay.com/yshalsager)](https://liberapay.com/yshalsager)

A bot that converts e-books to various formats, powered by [calibre](https://calibre-ebook.com/)!
It currently supports 34 input formats and 20 output formats.

You can start using it or adding it to your group [here on Telegram](https://t.me/ebook_converter_bot).

## Sponsors

Thanks to JetBrains for providing us with open-source free license!

[![JetBrains Logo](https://resources.jetbrains.com/storage/products/company/brand/logos/jb_beam.svg)](https://jb.gg/OpenSourceSupport)

## About the code:

This project is a modular bot, made using Python 3 and the following:

- [Telethon Library](https://github.com/LonamiWebs/Telethon/)
- [Calibre](https://calibre-ebook.com/)

## Bot features:

This bot aims to provide an easy way for telegram users to convert e-books from and to different formats.

It supports converting from the following formats:

```python
['azw', 'azw3', 'azw4', 'azw8', 'cb7', 'cbc', 'cbr', 'cbz', 'chm', 'djvu', 'docx',
 'doc', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'kfx', 'kfx-zip', 'kpf', 'lit',
 'lrf', 'mobi', 'odt', 'opf', 'pdb', 'pml', 'prc', 'rb', 'rtf', 'snb', 'tcr',
 'txt', 'txtz']
```

To the following formats:

```python
['azw3', 'docx', 'epub', 'fb2', 'htmlz', 'kfx', 'lit', 'lrf', 'mobi', 'oeb',
 'pdb', 'pdf', 'pmlz', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz', 'zip']
```

Some more features of the bot:

- Force book direction to be RTL
- Multilingual support, you can contribute and add your own languages if you want :).
- Flatten book's table of contents.

## Usage

- Forward any supported file to the bot and choose the required format to convert to, and in few seconds the bot will
  reply you with the converted file.
- The bot works in groups too. Reply with `/convert` to any file then do the same steps as in private.
- You can change the preferences of the bot such as language using `/settings` or `/preferences` commands.

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
  make i18n-compile 
  ```

## Setting up the bot

Before all, clone this repository.

### Using Docker

- Simply, run the following command:

```bash
docker-compose up --build -d
```

### Without Docker [NOT RECOMMENDED]

#### Python dependencies

It requires Python 3.7 with pip v19+ installed or poetry if you use it.

Clone the repository and run any of the following commands:

##### Using poetry

```bash
poetry install
```

##### Using Pip

```bash
pip install .
```

#### Database

The bot depends on sqlite database. Make sure that your system has it installed.

#### Other requirements

You can go through the Dockerfile to see how the bot requirements are being installed.

- The conversion process is done by utilizing [Calibre](https://calibre-ebook.com/) and its ebook-convert, so make sure
  you have it installed.
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
python3 -m ebook_converter_bot
```

### Internationalization (i18n)

The bot uses gettext for internationalization and makefile for running i18n tasks easily.

- First, generate .pot template using `make i18n-generate-messages`.
- Update the current translation files using `make i18n-merge`, then edit the translation strings.
- Compile the translation files using `make i18n-compile`.

To add a new language to the bot, run the following command (change 'ar' to your language code) then edit the new
language file with translation and compile.

```bash
LANG=ar make i18n-init-lang
```
