"""Force all tests onto an isolated temp DB — never touch ./data/app.db.

Must set env BEFORE any app.* import. Individual test modules that also
setdefault env remain compatible; this file wins for process-wide isolation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="oa_pytest_"))
_TEST_DB = _TEST_ROOT / "test.db"

# Override even if .env / shell already points at ./data
os.environ["APP_DATA_DIR"] = str(_TEST_ROOT)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ.setdefault("AGENT_ADAPTER", "mock")


def _assert_test_database() -> None:
    from app.config import settings

    url = settings.database_url.replace("\\", "/").lower()
    data_dir = str(settings.data_dir).replace("\\", "/").lower()
    if "/data/app.db" in url or data_dir.endswith("/data") and "oa_pytest_" not in data_dir:
        # Absolute project data path — refuse destructive fixtures
        if "oa_pytest_" not in url and "oa_pytest_" not in data_dir:
            raise RuntimeError(
                f"Refusing to run destructive DB fixtures against production DB: {settings.database_url}"
            )


def assert_safe_to_drop() -> None:
    """Call before Base.metadata.drop_all in tests."""
    from app.config import settings

    url = settings.database_url.replace("\\", "/").lower()
    root = str(_TEST_ROOT).replace("\\", "/").lower()
    if "oa_pytest_" not in url and root not in url:
        raise RuntimeError(
            f"Test tried to drop_all on non-isolated DB: {settings.database_url}"
        )


def safe_drop_all(bind) -> None:
    from app.db.models import Base

    assert_safe_to_drop()
    Base.metadata.drop_all(bind=bind)
