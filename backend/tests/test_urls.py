"""Tests for URL normalization and API URL building."""
from __future__ import annotations

from app.core.urls import (
    build_api_url,
    chat_completions_url,
    models_url,
    normalize_base_url,
)


def test_normalize_adds_scheme():
    assert normalize_base_url("localhost:8080") == "http://localhost:8080"


def test_normalize_strips_trailing_slash():
    assert normalize_base_url("https://host/v1/").endswith("/v1") is True
    assert not normalize_base_url("https://host/v1/").endswith("/v1/")


def test_normalize_collapses_duplicate_v1():
    url = normalize_base_url("https://host/v1/v1")
    assert "/v1/v1" not in url
    assert url.count("/v1") == 1


def test_build_api_url_appends_v1_when_missing():
    assert build_api_url("https://host", "/chat/completions") == "https://host/v1/chat/completions"


def test_build_api_url_preserves_single_v1():
    assert build_api_url("https://host/v1", "/chat/completions") == "https://host/v1/chat/completions"


def test_build_api_url_no_duplicate_v1():
    assert build_api_url("https://host/v1", "/chat/completions") == "https://host/v1/chat/completions"
    assert build_api_url("https://host/v1/v1", "/chat/completions") == "https://host/v1/chat/completions"


def test_chat_completions_url():
    assert chat_completions_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1/chat/completions"


def test_models_url_appends_v1():
    assert models_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/models"


def test_custom_path_kept():
    # A non-v1 trailing path is preserved.
    url = build_api_url("https://host/custom", "/chat/completions")
    assert url == "https://host/custom/v1/chat/completions"
