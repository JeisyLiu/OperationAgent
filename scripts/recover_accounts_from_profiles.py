"""Recover Account rows from leftover data/profiles/* after accidental DB wipe."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.constants import AccountStatus
from app.db.models import Account, Base
from app.db.session import SessionLocal, engine


def main() -> int:
    profiles = settings.data_dir / "profiles"
    if not profiles.is_dir():
        print(f"No profiles dir at {profiles}")
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    created = 0
    try:
        existing = {a.browser_profile for a in db.query(Account).all()}
        for folder in sorted(profiles.iterdir()):
            if not folder.is_dir():
                continue
            name = folder.name
            # expected: {platform}_{hex}
            if "_" not in name:
                print(f"skip (no platform prefix): {name}")
                continue
            platform, suffix = name.split("_", 1)
            rel = f"profiles/{name}"
            if rel in existing:
                print(f"exists: {rel}")
                continue
            account = Account(
                platform=platform.lower(),
                account_name=f"recovered-{platform}-{suffix[:6]}",
                browser_profile=rel,
                status=AccountStatus.PENDING_LOGIN.value,
            )
            db.add(account)
            created += 1
            print(f"created: {platform} → {rel}")
        db.commit()
    finally:
        db.close()

    print(f"Done. Recovered {created} account(s). Re-run「登录并启用」if session expired.")
    print("Note: LLM keys / content packages cannot be recovered without a DB backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
