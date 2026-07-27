"""Application configuration and paths."""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "LocalBench Studio"
APP_VERSION = "1.0.0"
SERVICE_NAME = "localbench-studio"


def default_data_dir() -> Path:
    """Return the OS-appropriate local data directory."""
    override = os.environ.get("LOCALBENCH_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "LocalBenchStudio"
    # Linux / macOS fallback
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "localbench-studio"
    return Path.home() / ".local" / "share" / "localbench-studio"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOCALBENCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Path("")  # filled by get_settings
    log_level: str = "INFO"
    secret: str = ""
    allow_plaintext_key_fallback: bool = False

    def ensure_directories(self) -> Path:
        data = self.data_dir
        for sub in ["", "exports", "logs", "backups", "benchmark_exports"]:
            (data / sub).mkdir(parents=True, exist_ok=True)
        return data

    @property
    def db_path(self) -> Path:
        return self.data_dir / "localbench.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "logs" / "app.log"

    def resolve_secret(self) -> str:
        """Return the configured secret, persisting a generated one if absent."""
        if self.secret:
            return self.secret
        secret_file = self.data_dir / "secret.key"
        if secret_file.exists():
            return secret_file.read_text(encoding="utf-8").strip()
        generated = secrets.token_urlsafe(32)
        secret_file.write_text(generated, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except OSError:
            pass
        return generated


_settings: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _settings
    if _settings is None or refresh:
        _settings = Settings()
        _settings.data_dir = default_data_dir()
        _settings.ensure_directories()
        _settings.resolve_secret()
    return _settings


def reset_settings_for_tests() -> None:
    """Clear cached settings (used by tests that override paths)."""
    global _settings
    _settings = None
