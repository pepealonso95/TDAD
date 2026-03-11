"""Shared local LLM configuration helpers for OpenAI-compatible runtimes.

The benchmark defaults now target a local llama.cpp server via its OpenAI-
compatible API. Legacy Ollama model env vars are still accepted as fallbacks
for model naming only, so existing local setups do not need to rename every
variable immediately.
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_LOCAL_LLM_RUNTIME = "llama.cpp"
DEFAULT_LOCAL_LLM_API_BASE = "http://127.0.0.1:8080/v1"
DEFAULT_LOCAL_LLM_API_KEY = "local"
DEFAULT_LOCAL_LLM_PROVIDER = "openai"


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = str(os.getenv(name, "")).strip()
        if value:
            return value
    return default


def normalize_openai_api_base(api_base: str) -> str:
    value = (api_base or DEFAULT_LOCAL_LLM_API_BASE).strip().rstrip("/")
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def build_openai_endpoint(api_base: str, suffix: str) -> str:
    suffix = suffix if suffix.startswith("/") else f"/{suffix}"
    return normalize_openai_api_base(api_base) + suffix


def get_local_llm_runtime() -> str:
    return _first_env("LOCAL_LLM_RUNTIME", "LLAMA_CPP_RUNTIME", default=DEFAULT_LOCAL_LLM_RUNTIME)


def get_local_llm_api_base() -> str:
    return normalize_openai_api_base(
        _first_env("LOCAL_LLM_API_BASE", "LLAMA_CPP_API_BASE", default=DEFAULT_LOCAL_LLM_API_BASE)
    )


def get_local_llm_api_key() -> str:
    return _first_env("LOCAL_LLM_API_KEY", "LLAMA_CPP_API_KEY", default=DEFAULT_LOCAL_LLM_API_KEY)


def get_local_llm_provider() -> str:
    return _first_env("LOCAL_LLM_PROVIDER", "LLAMA_CPP_PROVIDER", default=DEFAULT_LOCAL_LLM_PROVIDER)


def get_qwen_model_name(default_model: str = "qwen3-coder:30b", *, mini: bool = False) -> str:
    if mini:
        return _first_env(
            "QWEN_MINI_MODEL",
            "QWEN_MINI_LLAMACPP_MODEL",
            "QWEN_MINI_OLLAMA_MODEL",
            default=default_model,
        )
    return _first_env(
        "QWEN_MODEL",
        "QWEN_LLAMACPP_MODEL",
        "QWEN_OLLAMA_MODEL",
        default=default_model,
    )


def openai_headers(api_key: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = (api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def ensure_local_llm_server_ready(
    *,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = 5.0,
    session: Any | None = None,
) -> str:
    """Check the local OpenAI-compatible server and return the models URL used."""
    models_url = build_openai_endpoint(api_base or get_local_llm_api_base(), "/models")
    requester = session or requests
    response = requester.get(
        models_url,
        headers=openai_headers(api_key or get_local_llm_api_key()),
        timeout=timeout,
    )
    response.raise_for_status()
    return models_url
