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

from app.schemas.bulk import BulkActionRequest, BulkActionResponse

from app.services.bulk_actions import bulk_actions_service

from app.services.account_service import account_service

from app.services.event_bus import emit_readiness_changed



router = APIRouter(prefix="/api/accounts", tags=["accounts"])



_profile_runtimes: dict[int, PlaywrightRuntime] = {}





def _account_response(account, db: Session) -> AccountResponse:

    return AccountResponse(

        id=account.id,

        platform=account.platform,

        account_name=account.account_name,

        browser_profile=account.browser_profile,

        persona=account_service.resolve_persona(account, db) or None,

        language=account.language,

        description=account.description,

        role_id=account.role_id,

        role_tags=account_service.parse_role_tags(account),

        role_display_name=account_service.resolve_role_display_name(account, db),

        skill=account_service.resolve_skill(account, db),

        template_skill=account_service.resolve_template_skill(account, db),

        status=account.status,

        created_at=account.created_at,

    )





@router.get("", response_model=list[AccountResponse])

def list_accounts(

    platform: str | None = None,

    db: Session = Depends(get_db),

) -> list[AccountResponse]:

    return [_account_response(a, db) for a in account_service.list_accounts(db, platform=platform)]





@router.post("", response_model=AccountResponse)

def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountResponse:

    try:

        require_platform(payload.platform, db=db)

        account_service.validate_role_id(payload.role_id, db)

    except PlatformNotFoundError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except PlatformDisabledError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc



    return _account_response(

        account_service.create(

            db,

            platform=payload.platform.lower(),

            account_name=payload.account_name,

            persona=payload.persona,

            language=payload.language,

            description=payload.description,

            role_id=payload.role_id,

            role_tags=payload.role_tags,

            skill=payload.skill,

        ),

        db,

    )





@router.post("/bulk", response_model=BulkActionResponse)

def bulk_accounts(payload: BulkActionRequest, db: Session = Depends(get_db)) -> BulkActionResponse:

    try:

        result = bulk_actions_service.bulk_accounts(

            db,

            ids=payload.ids,

            action=payload.action,

            blocked_ids=set(_profile_runtimes.keys()),

            role_id=payload.role_id,

            replace_skill=payload.replace_skill,

        )

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.succeeded and payload.action in {"delete", "disable", "enable", "set_role"}:

        emit_readiness_changed()

    return result





@router.get("/{account_id}", response_model=AccountResponse)

def get_account(account_id: int, db: Session = Depends(get_db)) -> AccountResponse:

    account = account_service.get(db, account_id)

    if account is None:

        raise HTTPException(status_code=404, detail="Account not found")

    return _account_response(account, db)





@router.patch("/{account_id}", response_model=AccountResponse)

def patch_account(

    account_id: int,

    payload: AccountUpdate,

    db: Session = Depends(get_db),

) -> AccountResponse:

    account = account_service.get(db, account_id)

    if account is None:

        raise HTTPException(status_code=404, detail="Account not found")

    try:

        updated = account_service.update(

            db,

            account,

            account_name=payload.account_name,

            persona=payload.persona,

            language=payload.language,

            description=payload.description,

            status=payload.status,

            role_id=payload.role_id,

            role_tags=payload.role_tags,

            skill=payload.skill,

            clear_skill_override=payload.clear_skill_override,

        )

    except ValueError as exc:

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _account_response(updated, db)





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

    return await _open_profile_for_account(account_id, db)





@router.post("/{account_id}/login-and-activate", response_model=AccountActionResponse)

async def login_and_activate(account_id: int, db: Session = Depends(get_db)) -> AccountActionResponse:

    """Open browser for first-time login; client confirms then calls mark-active."""

    return await _open_profile_for_account(

        account_id,

        db,

        message="浏览器已打开。请完成登录（含验证码）后，在应用中点击确认以启用账号。",

    )





async def _open_profile_for_account(

    account_id: int,

    db: Session,

    message: str = "Browser opened. Complete login manually, then call mark-active.",

) -> AccountActionResponse:

    account = account_service.get(db, account_id)

    if account is None:

        raise HTTPException(status_code=404, detail="Account not found")



    try:

        require_platform(account.platform, db=db)

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

        detail = str(exc)

        if "Executable doesn't exist" in detail or "playwright install" in detail.lower():

            detail = "浏览器引擎未就绪，正在尝试自动安装失败。请点 Dashboard「重试修复」后再试「登录并启用」。"

        raise HTTPException(

            status_code=500,

            detail=detail if detail.startswith("已") or "浏览器" in detail else f"打开浏览器失败：{detail}",

        ) from exc



    _profile_runtimes[account_id] = runtime



    return AccountActionResponse(status="opened", message=message)





@router.post("/{account_id}/mark-active", response_model=AccountResponse)

async def mark_active(account_id: int, db: Session = Depends(get_db)) -> AccountResponse:

    account = account_service.get(db, account_id)

    if account is None:

        raise HTTPException(status_code=404, detail="Account not found")



    runtime = _profile_runtimes.pop(account_id, None)

    if runtime is not None:

        await runtime.close()



    account = account_service.mark_active(db, account)

    emit_readiness_changed()

    return _account_response(account, db)





@router.post("/{account_id}/check-session", response_model=SessionCheckResponse)

def check_session(account_id: int, db: Session = Depends(get_db)) -> SessionCheckResponse:

    account = account_service.get(db, account_id)

    if account is None:

        raise HTTPException(status_code=404, detail="Account not found")



    logged_in = account.status == "ACTIVE"

    message = (

        "Account is active; profile should retain session."

        if logged_in

        else "Account not active. Use「登录并启用」to complete login."

    )

    return SessionCheckResponse(

        logged_in=logged_in,

        account_status=account.status,

        message=message,

    )


