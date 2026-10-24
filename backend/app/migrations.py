from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import Settings

logger = logging.getLogger(__name__)


def backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def run_migrations(settings: Settings) -> None:
    settings.ensure_directories()
    config = Config(str(backend_dir() / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir() / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))
    if str(backend_dir()) not in sys.path:
        sys.path.insert(0, str(backend_dir()))
    logger.info("Applying database migrations")
    command.upgrade(config, "head")
