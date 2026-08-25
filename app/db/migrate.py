import logging

from sqlalchemy import inspect, text

from app.db.session import engine

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Lightweight SQLite migrations for MVP (add missing columns)."""
    if not str(engine.url).startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "content_assets" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("content_assets")}
    if "attachments_json" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE content_assets ADD COLUMN attachments_json TEXT"))
        logger.info("Migration: added content_assets.attachments_json")
