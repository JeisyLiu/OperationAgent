import logging
from datetime import datetime

from sqlalchemy import inspect, text

from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

LLM_MODELS_DDL = """
CREATE TABLE IF NOT EXISTS llm_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    base_url TEXT,
    model VARCHAR(128),
    api_key_enc TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    max_concurrency INTEGER NOT NULL DEFAULT 4,
    timeout_sec INTEGER NOT NULL DEFAULT 60,
    extra_json TEXT,
    updated_at DATETIME
)
"""


def run_migrations() -> None:
    """Lightweight SQLite migrations for MVP (add missing columns / tables)."""
    if not str(engine.url).startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "content_assets" in table_names:
            columns = {col["name"] for col in inspector.get_columns("content_assets")}
            if "attachments_json" not in columns:
                conn.execute(text("ALTER TABLE content_assets ADD COLUMN attachments_json TEXT"))
                logger.info("Migration: added content_assets.attachments_json")

        conn.execute(text(LLM_MODELS_DDL))
        logger.info("Migration: ensured llm_models table exists")

        if "execution_logs" in table_names:
            columns = {col["name"] for col in inspector.get_columns("execution_logs")}
            execution_log_columns = {
                "tool_name": "TEXT",
                "status": "TEXT",
                "duration_ms": "INTEGER",
                "prompt_tokens": "INTEGER",
                "completion_tokens": "INTEGER",
                "total_tokens": "INTEGER",
                "payload_json": "TEXT",
                "started_at": "DATETIME",
            }
            for col_name, col_type in execution_log_columns.items():
                if col_name not in columns:
                    conn.execute(
                        text(f"ALTER TABLE execution_logs ADD COLUMN {col_name} {col_type}")
                    )
                    logger.info("Migration: added execution_logs.%s", col_name)

    _migrate_ai_settings_to_llm_models()


def _migrate_ai_settings_to_llm_models() -> None:
    from app.db.models import AiSettings, LlmModel

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "ai_settings" not in table_names:
        logger.info("Migration: ai_settings table absent, skip legacy LLM copy")
        return
    if "llm_models" not in table_names:
        return

    db = SessionLocal()
    try:
        if db.query(LlmModel).count() > 0:
            return
        legacy = db.query(AiSettings).order_by(AiSettings.id.desc()).first()
        if legacy is None:
            return
        provider = (legacy.provider or "openai").lower()
        if provider not in {"openai", "qwen"}:
            provider = "openai"
        row = LlmModel(
            alias="Default",
            provider=provider,
            base_url=legacy.base_url,
            model=legacy.model,
            api_key_enc=legacy.api_key_enc,
            enabled=1,
            priority=0,
            max_concurrency=4,
            timeout_sec=60,
            updated_at=legacy.updated_at or datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        logger.info("Migration: copied ai_settings into llm_models id=%s", row.id)
    finally:
        db.close()
