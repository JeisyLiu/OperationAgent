#!/usr/bin/env python3
"""Create all database tables."""

from app.db.models import Base
from app.db.session import engine
from app.config import settings


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized at {settings.database_url}")


if __name__ == "__main__":
    main()
