"""Credential storage via OS keyring with explicit fallback handling."""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import SERVICE_NAME, get_settings

log = logging.getLogger(__name__)


class KeyringUnavailable(RuntimeError):
    """Raised when no backend can securely store secrets."""


def _import_keyring():
    try:
        import keyring  # type: ignore

        # Probe for a usable backend.
        backend = keyring.get_keyring()
        if backend is None:
            return None
        name = getattr(backend, "name", str(backend))
        # Some "null" backends silently store nothing.
        if "fail" in name.lower() or "null" in name.lower() or "disable" in name.lower():
            return None
        return keyring
    except Exception as exc:  # pragma: no cover - environment specific
        log.debug("keyring unavailable: %s", exc)
        return None


def is_keyring_available() -> bool:
    return _import_keyring() is not None


def _profile_key(profile_id: str) -> str:
    return f"profile:{profile_id}"


def store_api_key(profile_id: str, api_key: str) -> str:
    """Store the API key. Returns the storage method used.

    Returns one of: "keyring", "env", "session", "plaintext".
    Plaintext is only used when explicitly enabled via settings.
    """
    settings = get_settings()
    keyring = _import_keyring()
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, _profile_key(profile_id), api_key)
            return "keyring"
        except Exception as exc:  # pragma: no cover
            log.warning("keyring storage failed (%s); falling back", exc)
    if settings.allow_plaintext_key_fallback:
        log.warning(
            "Storing API key for profile %s in plaintext (fallback enabled).", profile_id
        )
        return "plaintext"
    # Not stored durably — caller should treat as session-only.
    return "session"


def get_api_key(profile_id: str) -> Optional[str]:
    keyring = _import_keyring()
    if keyring is not None:
        try:
            return keyring.get_password(SERVICE_NAME, _profile_key(profile_id))
        except Exception:  # pragma: no cover
            return None
    return None


def delete_api_key(profile_id: str) -> None:
    keyring = _import_keyring()
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, _profile_key(profile_id))
        except Exception:
            pass


def resolve_api_key(
    profile_id: str,
    *,
    stored_value: Optional[str],
    env_var: Optional[str],
    session_key: Optional[str],
) -> tuple[Optional[str], str]:
    """Resolve an API key from session, stored secret, or env var.

    Returns (api_key_or_None, source). Sources: "session", "keyring", "env", "none".
    Never raises for missing env vars.
    """
    if session_key:
        return session_key, "session"
    keyring_value = get_api_key(profile_id) if stored_value else None
    if keyring_value:
        return keyring_value, "keyring"
    if env_var:
        import os

        env_val = os.environ.get(env_var)
        if env_val:
            return env_val, "env"
    return None, "none"
