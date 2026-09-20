"""RU/EN localization.

Strings live in locales/<lang>.json and support .format() substitution,
e.g. t('check_done', lang, found=3, total=5). Missing keys fall back
to DEFAULT_LANG, then to the key itself. To add a language, drop in
locales/<code>.json with the same key set and register the code in
SUPPORTED_LANGUAGES.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {
    "ru": "RU",
    "en": "EN",
}

DEFAULT_LANG = "ru"

_LOCALES_DIR = Path(__file__).parent / "locales"


def _load_table(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("Locale file not found: %s", path)
    except Exception as e:
        logger.error("Failed to read %s: %s", path, e)
    return {}


STRINGS = {lang: _load_table(lang) for lang in SUPPORTED_LANGUAGES}


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Look up key in lang with kwargs substitution and fallbacks."""
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
