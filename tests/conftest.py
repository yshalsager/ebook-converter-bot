import os

# Tests never talk to Telegram; fake config so importing the package doesn't need real secrets.
for key, value in {
    "API_KEY": "1",
    "API_HASH": "test",
    "TG_BOT_TOKEN": "1:test",
}.items():
    os.environ.setdefault(key, value)
