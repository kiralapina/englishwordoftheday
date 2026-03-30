"""Optional short explanation generator for grammar feedback."""

from __future__ import annotations

import logging

import requests

from grammar import config

logger = logging.getLogger(__name__)


def generate_short_explanation(prompt: str) -> str | None:
    if not config.grammar_llm_explanations_enabled():
        return None
    api_key = config.grammar_openai_api_key()
    if not api_key:
        return None

    base_url = config.grammar_openai_base_url()
    timeout = config.grammar_llm_timeout()

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.grammar_openai_model(),
                "messages": [
                    {
                        "role": "system",
                        "content": "Write a short grammar explanation in Russian in at most 280 characters.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 120,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return content.strip() if content else None
    except Exception as e:
        logger.warning("Grammar explanation LLM generation failed: %s", e)
        return None
