# -*- coding: utf-8 -*-
"""Автопополнение данных о слове через Free Dictionary API и перевод (MyMemory)."""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DICTIONARY_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
# Бесплатный перевод (MyMemory), лимит ~1000 запросов/день без ключа
TRANSLATE_API_URL = "https://api.mymemory.translated.net/get?q={text}&langpair=en|ru"


def fetch_word_data(word: str) -> Optional[dict]:
    """
    Получить данные о слове: транскрипция (IPA), определение на английском, пример.
    При необходимости — перевод на русский через MyMemory.
    Возвращает dict: translation, transcription, example_sentence или None при ошибке.
    """
    word = word.strip().lower()
    if not word:
        return None
    out = {"translation": "", "transcription": "", "example_sentence": ""}
    try:
        r = requests.get(DICTIONARY_API_URL.format(word=word), timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        entry = data[0]
        # Транскрипция: первый доступный phonetic text
        phonetics = entry.get("phonetics") or []
        for p in phonetics:
            if p.get("text"):
                out["transcription"] = p["text"].strip()
                break
        # Определение и пример из первого meaning
        meanings = entry.get("meanings") or []
        for m in meanings:
            defs_list = m.get("definitions") or []
            for d in defs_list:
                if d.get("definition"):
                    out["example_sentence"] = (d.get("example") or d.get("definition") or "")[:500]
                    out["_definition_en"] = d["definition"][:300]
                    break
            if out["example_sentence"] or out.get("_definition_en"):
                break
        if not out.get("_definition_en") and meanings:
            first_def = (meanings[0].get("definitions") or [{}])[0]
            out["_definition_en"] = (first_def.get("definition") or "")[:300]
        # Перевод на русский (опционально): переводим первое определение или само слово
        text_to_translate = out.get("_definition_en") or word
        try:
            tr = requests.get(TRANSLATE_API_URL.format(text=requests.utils.quote(text_to_translate)), timeout=5)
            if tr.ok:
                j = tr.json()
                if j.get("responseStatus") == 200 and j.get("responseData", {}).get("translatedText"):
                    out["translation"] = j["responseData"]["translatedText"].strip()[:400]
        except Exception as e:
            logger.debug("Translation API skip: %s", e)
        out.pop("_definition_en", None)
        if not out["translation"] and out.get("_definition_en"):
            out["translation"] = out["_definition_en"][:400]
        return out
    except requests.RequestException as e:
        logger.warning("Dictionary API error for %s: %s", word, e)
        return None
    except Exception as e:
        logger.exception("fetch_word_data error: %s", e)
        return None
