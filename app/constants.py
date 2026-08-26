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
    WAITING_HUMAN = "WAITING_HUMAN"


class StepStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WAITING_HUMAN = "WAITING_HUMAN"


class AccountStatus(StrEnum):
    PENDING_LOGIN = "PENDING_LOGIN"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class FailureCode(StrEnum):
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_BLOCKED = "CAPTCHA_BLOCKED"
    UPLOAD_TIMEOUT = "UPLOAD_TIMEOUT"
    UI_CHANGED = "UI_CHANGED"
    UNKNOWN = "UNKNOWN"


NON_RETRYABLE_FAILURES = {
    FailureCode.LOGIN_REQUIRED.value,
    FailureCode.CAPTCHA_BLOCKED.value,
}

RETRY_BACKOFF_SECONDS = [60, 300, 900]

RETRY_ALLOWED_STATUSES = {
    JobStatus.FAILED.value,
    JobStatus.DEAD.value,
    JobStatus.CANCELLED.value,
    JobStatus.RETRY.value,
}

REPUBLISH_ALLOWED_STATUSES = {
    JobStatus.SUCCESS.value,
    JobStatus.FAILED.value,
    JobStatus.DEAD.value,
    JobStatus.CANCELLED.value,
    JobStatus.WAITING_HUMAN.value,
    JobStatus.RETRY.value,
}

RUNNING_JOB_STATUSES = {
    JobStatus.PENDING.value,
    JobStatus.CLAIMED.value,
    JobStatus.EXECUTING.value,
    JobStatus.VERIFYING.value,
}


def utcnow() -> datetime:
    return datetime.utcnow()


def classify_failure(message: str) -> str:
    lower = message.lower()
    if any(k in lower for k in ("login", "sign in", "not logged", "session expired")):
        return FailureCode.LOGIN_REQUIRED.value
    if any(k in lower for k in ("captcha", "verify you are human", "verification required")):
        return FailureCode.CAPTCHA_BLOCKED.value
    if any(k in lower for k in ("upload timeout", "upload failed", "timeout")):
        return FailureCode.UPLOAD_TIMEOUT.value
    if any(k in lower for k in ("ui changed", "selector", "element not found", "page changed")):
        return FailureCode.UI_CHANGED.value
    return FailureCode.UNKNOWN.value
