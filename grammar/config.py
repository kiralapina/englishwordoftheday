"""Configuration and feature flags for the grammar module."""

import os


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def grammar_module_enabled() -> bool:
    return _env_flag("GRAMMAR_MODULE_ENABLED", default=True)


def grammar_llm_explanations_enabled() -> bool:
    return _env_flag("GRAMMAR_LLM_EXPLANATIONS_ENABLED", default=False)


def grammar_llm_transformation_check_enabled() -> bool:
    return _env_flag("GRAMMAR_LLM_TRANSFORMATION_CHECK_ENABLED", default=True)


def grammar_review_enabled() -> bool:
    return _env_flag("GRAMMAR_REVIEW_ENABLED", default=True)


def grammar_openai_api_key() -> str:
    return (os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


def grammar_openai_base_url() -> str:
    return (os.getenv("BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")


def grammar_openai_model() -> str:
    return os.getenv("GRAMMAR_OPENAI_MODEL", "gpt-4o-mini").strip()


def grammar_llm_timeout() -> int:
    try:
        return int(os.getenv("LLM_TIMEOUT", "15"))
    except ValueError:
        return 15
