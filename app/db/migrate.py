import logging
from datetime import datetime

from sqlalchemy import inspect, text

from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)

SKILL_ROLES_DDL = """
CREATE TABLE IF NOT EXISTS skill_roles (
    id VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(128) NOT NULL,
    description TEXT,
    persona TEXT,
    skill_json TEXT NOT NULL,
    updated_at DATETIME
)
"""

SKILL_ROLE_OVERLAYS_DDL = """
CREATE TABLE IF NOT EXISTS skill_role_overlays (
    role_id VARCHAR(64) NOT NULL,
    platform VARCHAR(32) NOT NULL,
    skill_json TEXT,
    persona_suffix TEXT,
    updated_at DATETIME,
    PRIMARY KEY (role_id, platform)
)
"""

CUSTOM_PLATFORMS_DDL = """
CREATE TABLE IF NOT EXISTS custom_platforms (
    id VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(128) NOT NULL,
    region VARCHAR(32) NOT NULL DEFAULT 'global',
    home_url TEXT NOT NULL,
    login_url TEXT,
    upload_url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    media_types_json TEXT,
    variant_schema_json TEXT,
    default_persona TEXT,
    default_skill_json TEXT,
    publish_options_json TEXT,
    preferred_adapter VARCHAR(64),
    created_at DATETIME
)
"""

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

OPERATION_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS operation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    asset_id INTEGER,
    account_ids_json TEXT,
    variant_ids_json TEXT,
    input_json TEXT,
    summary TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    error_message TEXT,
    created_at DATETIME,
    completed_at DATETIME
)
"""

OPERATION_STEPS_DDL = """
CREATE TABLE IF NOT EXISTS operation_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    account_id INTEGER,
    platform VARCHAR(32),
    variant_id INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    attempt INTEGER NOT NULL DEFAULT 1,
    model_id INTEGER,
    model_alias VARCHAR(128),
    skill_json TEXT,
    persona TEXT,
    messages_json TEXT,
    response_text TEXT,
    parsed_json TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    duration_ms INTEGER,
    error_message TEXT,
    created_at DATETIME,
    FOREIGN KEY (run_id) REFERENCES operation_runs(id)
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

        conn.execute(text(SKILL_ROLES_DDL))
        conn.execute(text(SKILL_ROLE_OVERLAYS_DDL))
        conn.execute(text(CUSTOM_PLATFORMS_DDL))
        conn.execute(text(OPERATION_RUNS_DDL))
        conn.execute(text(OPERATION_STEPS_DDL))
        logger.info("Migration: ensured skill_roles, custom_platforms, and operation audit tables exist")

        if "accounts" in table_names:
            account_columns = {col["name"] for col in inspector.get_columns("accounts")}
            if "role_id" not in account_columns:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN role_id VARCHAR(64)"))
                logger.info("Migration: added accounts.role_id")
            if "role_tags_json" not in account_columns:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN role_tags_json TEXT"))
                logger.info("Migration: added accounts.role_tags_json")

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
    _seed_skill_templates()


def _seed_skill_templates() -> None:
    from app.services.skill_seed import seed_skill_templates

    db = SessionLocal()
    try:
        count = seed_skill_templates(db)
        if count:
            logger.info("Migration: seeded %s skill role templates", count)
    finally:
        db.close()


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
