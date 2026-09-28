"""URL and value normalization helpers."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def normalize_base_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL.

    Rules:
    * Add a scheme if missing.
    * Strip trailing slashes.
    * Collapse duplicate ``/v1`` segments (never produce ``/v1/v1``).
    """
    if not base_url:
        return ""
    url = base_url.strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s != ""]
    deduped: list[str] = []
    for s in segments:
        if s == "v1" and deduped and deduped[-1] == "v1":
            continue
        deduped.append(s)
    new_path = "/" + "/".join(deduped) if deduped else ""
    return urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))


def _split_base_and_v1(base_url: str) -> tuple[str, str]:
    """Return (base_path_without_v1, "v1" | "")."""
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    segments = [s for s in parsed.path.split("/") if s != ""]
    v1 = ""
    if segments and segments[-1] == "v1":
        segments = segments[:-1]
        v1 = "v1"
    base_path = "/" + "/".join(segments) if segments else ""
    return base_path, v1


def build_api_url(base_url: str, api_path: str) -> str:
    """Append an API path to a base URL, ensuring exactly one /v1 prefix.

    Examples:
      build_api_url("https://h", "/chat/completions") -> "https://h/v1/chat/completions"
      build_api_url("https://h/v1", "/chat/completions") -> "https://h/v1/chat/completions"
      build_api_url("https://h/v1/v1", "/chat/completions") -> "https://h/v1/chat/completions"
      build_api_url("https://h/custom", "/chat/completions") -> "https://h/custom/v1/chat/completions"
    """
    normalized = normalize_base_url(base_url)
    if not normalized:
        return api_path
    parsed = urlparse(normalized)
    segments = [s for s in parsed.path.split("/") if s != ""]
    # Explicit versioned prefixes (Z.ai v4, Gemini v1beta/openai) are
    # complete API roots. Only unversioned roots need the legacy /v1 default.
    if not any(re.fullmatch(r"v\d+(?:alpha|beta)?\d*", part) for part in segments):
        segments.append("v1")
    clean_path = "/" + "/".join(segments)
    api_path = api_path if api_path.startswith("/") else "/" + api_path
    # Prevent /v1/v1 if api_path itself begins with /v1.
    if api_path == "/v1" or api_path.startswith("/v1/"):
        api_path = api_path[len("/v1"):]
    return urlunparse((parsed.scheme, parsed.netloc, clean_path + api_path, "", "", ""))


def chat_completions_url(base_url: str) -> str:
    return build_api_url(base_url, "/chat/completions")


def models_url(base_url: str) -> str:
    return build_api_url(base_url, "/models")
