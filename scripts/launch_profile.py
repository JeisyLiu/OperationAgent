#!/usr/bin/env python3
"""Open a persistent browser profile for manual login."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.constants import PLATFORM_URLS
from app.runtime.playwright_runtime import PlaywrightRuntime


async def main() -> None:
    parser = argparse.ArgumentParser(description="Launch browser profile for login")
    parser.add_argument("profile", help="Profile path relative to data/ or absolute")
    parser.add_argument("--platform", default="tiktok", help="Platform key for default URL")
    parser.add_argument("--url", default=None, help="Override start URL")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    if not profile_path.is_absolute():
        profile_path = settings.data_dir / profile_path

    url = args.url or PLATFORM_URLS.get(args.platform, "https://www.google.com")
    runtime = PlaywrightRuntime()
    await runtime.open_profile(profile_path, url=url)
    print(f"Opened profile {profile_path} at {url}. Press Ctrl+C to close.")
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
