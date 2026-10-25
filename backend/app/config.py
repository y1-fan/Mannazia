from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Defaults are relative so the backend can be run directly during development.
# Docker Compose overrides these with /config, /data and /books.
DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_BOOKS_DIR = Path("books")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANNAZIA_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Mannazia"
    version: str = "0.1.0"
    environment: str = "production"
    log_level: str = "INFO"

    config_dir: Path = DEFAULT_CONFIG_DIR
    data_dir: Path = DEFAULT_DATA_DIR
    books_dir: Path = DEFAULT_BOOKS_DIR
    frontend_dir: Path | None = None
    database_url: str | None = None

    # Network / SSRF controls
    allow_private_networks: bool = False
    allowed_private_hosts: str = ""
    max_manifest_bytes: int = 8 * 1024 * 1024
    max_info_bytes: int = 2 * 1024 * 1024
    max_image_bytes: int = 200 * 1024 * 1024
    max_redirects: int = 5
    http_timeout: float = 30.0
    http_connect_timeout: float = 10.0
    http_proxy: str | None = None
    user_agent: str = "Mannazia/0.1 (self-hosted IIIF library)"

    # Downloads
    download_concurrency: int = 3
    # 0 keeps the original resolution. A positive value caps page downloads.
    download_max_width: int = 0
    cover_max_width: int = 1200
    download_image_format: str = "jpg"
    download_retries: int = 3
    download_retry_backoff: float = 0.75
    auto_resume_downloads: bool = False

    # Reader thumbnail cache
    page_thumbnails_enabled: bool = True
    thumbnail_concurrency: int = 4
    thumbnail_max_bytes: int = 32 * 1024 * 1024

    # Reading / UI
    preview_ttl_seconds: int = 900

    @field_validator("download_concurrency", "thumbnail_concurrency")
    @classmethod
    def _valid_concurrency(cls, value: int) -> int:
        return max(1, min(value, 16))

    @field_validator("download_retries")
    @classmethod
    def _valid_retries(cls, value: int) -> int:
        return max(1, min(value, 10))

    @field_validator("http_timeout", "http_connect_timeout")
    @classmethod
    def _valid_timeout(cls, value: float) -> float:
        return max(1.0, min(value, 600.0))

    @field_validator("max_redirects")
    @classmethod
    def _valid_redirects(cls, value: int) -> int:
        return max(0, min(value, 10))

    @field_validator("download_max_width")
    @classmethod
    def _valid_width(cls, value: int) -> int:
        if value == 0:
            return 0
        return max(200, min(value, 12000))

    @field_validator("cover_max_width")
    @classmethod
    def _valid_cover_width(cls, value: int) -> int:
        return max(300, min(value, 4000))

    @field_validator("http_proxy")
    @classmethod
    def _valid_proxy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("MANNAZIA_HTTP_PROXY must be an http:// or https:// proxy URL")
        return value

    @field_validator("download_image_format")
    @classmethod
    def _valid_format(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"jpg", "png", "webp"}:
            raise ValueError("MANNAZIA_DOWNLOAD_IMAGE_FORMAT must be jpg, png or webp")
        return value

    @field_validator("books_dir", "data_dir", "config_dir")
    @classmethod
    def _expand_path(cls, value: Path) -> Path:
        return value.expanduser()

    @cached_property
    def allowed_private_host_set(self) -> frozenset[str]:
        hosts: set[str] = set()
        for item in re.split(r"[,\s]+", self.allowed_private_hosts):
            host = item.strip().lower().rstrip(".")
            if not host:
                continue
            # Hostnames only. Administrator exception, never a wildcard.
            if "/" in host or ":" in host or "*" in host:
                raise ValueError(
                    "MANNAZIA_ALLOWED_PRIVATE_HOSTS accepts exact hostnames only "
                    f"(invalid entry: {item!r})"
                )
            hosts.add(host)
        return frozenset(hosts)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "mannazia.db"

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.database_path.as_posix()}"

    def ensure_directories(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.books_dir):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
