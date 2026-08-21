from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class AccountStatus(StrEnum):
    PENDING_LOGIN = "PENDING_LOGIN"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


RETRY_BACKOFF_SECONDS = [60, 300, 900]

PLATFORM_URLS = {
    "tiktok": "https://www.tiktok.com/",
    "youtube": "https://www.youtube.com/",
    "reddit": "https://www.reddit.com/",
}


def utcnow() -> datetime:
    return datetime.utcnow()
