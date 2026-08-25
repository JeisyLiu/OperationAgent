import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.platforms import (
    PlatformDisabledError,
    PlatformNotFoundError,
    get_open_url,
    require_platform,
)
from app.runtime.playwright_runtime import PlaywrightRuntime
from app.schemas.accounts import (
    AccountActionResponse,
    AccountCreate,
    AccountResponse,
    AccountUpdate,
    SessionCheckResponse,
)
from app.services.account_service import account_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

_profile_runtimes: dict[int, PlaywrightRuntime] = {}


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    platform: str | None = None,
    db: Session = Depends(get_db),
) -> list[AccountResponse]:
    return account_service.list_accounts(db, platform=platform)


@router.post("", response_model=AccountResponse)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountResponse:
    try:
        require_platform(payload.platform)
    except PlatformNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PlatformDisabledError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return account_service.create(
        db,
        platform=payload.platform.lower(),
        account_name=payload.account_name,
        persona=payload.persona,
        language=payload.language,
        description=payload.description,
    )


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db)) -> AccountResponse:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.patch("/{account_id}", response_model=AccountResponse)
def patch_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
) -> AccountResponse:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account_service.update(
        db,
        account,
        account_name=payload.account_name,
        persona=payload.persona,
        language=payload.language,
        description=payload.description,
        status=payload.status,
    )


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if account_id in _profile_runtimes:
        raise HTTPException(
            status_code=400,
            detail="Close the open profile browser before deleting this account",
        )

    account_service.delete(db, account)
    return {"status": "deleted", "message": "Account removed. Profile directory was kept on disk."}


@router.post("/{account_id}/open-profile", response_model=AccountActionResponse)
async def open_profile(account_id: int, db: Session = Depends(get_db)) -> AccountActionResponse:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        require_platform(account.platform)
        url = get_open_url(account.platform)
    except PlatformNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Account has unknown platform '{account.platform}'. Delete and recreate the account.",
        ) from exc
    except PlatformDisabledError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if account_id in _profile_runtimes:
        await _profile_runtimes[account_id].close()
        del _profile_runtimes[account_id]

    runtime = PlaywrightRuntime()
    profile_path = account_service.resolve_profile_path(account)
    try:
        await runtime.open_profile(profile_path, url=url)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open browser profile: {exc}",
        ) from exc

    _profile_runtimes[account_id] = runtime

    return AccountActionResponse(
        status="opened",
        message="Browser opened. Complete login manually, then call mark-active.",
    )


@router.post("/{account_id}/mark-active", response_model=AccountResponse)
async def mark_active(account_id: int, db: Session = Depends(get_db)) -> AccountResponse:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    runtime = _profile_runtimes.pop(account_id, None)
    if runtime is not None:
        await runtime.close()

    return account_service.mark_active(db, account)


@router.post("/{account_id}/check-session", response_model=SessionCheckResponse)
def check_session(account_id: int, db: Session = Depends(get_db)) -> SessionCheckResponse:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    logged_in = account.status == "ACTIVE"
    message = (
        "Account is active; profile should retain session."
        if logged_in
        else "Account not active. Open profile and complete login, then mark-active."
    )
    return SessionCheckResponse(
        logged_in=logged_in,
        account_status=account.status,
        message=message,
    )
