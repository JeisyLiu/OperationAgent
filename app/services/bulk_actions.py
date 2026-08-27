import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.constants import AccountStatus, utcnow
from app.schemas.bulk import BulkActionResponse, BulkFailureItem
from app.services.account_service import account_service
from app.services.content_service import content_service
from app.services.job_service import job_service
from app.services.llm_model_service import llm_model_service

ACCOUNT_ACTIONS = frozenset({"delete", "disable", "enable", "set_role"})
VARIANT_ACTIONS = frozenset({"delete", "enqueue"})
LLM_ACTIONS = frozenset({"delete", "enable", "disable"})
JOB_ACTIONS = frozenset({"cancel", "retry"})


def _run_bulk(action: str, ids: list[int], handler: Callable[[int], None]) -> BulkActionResponse:
    succeeded: list[int] = []
    failed: list[BulkFailureItem] = []
    for item_id in ids:
        try:
            handler(item_id)
            succeeded.append(item_id)
        except Exception as exc:
            failed.append(BulkFailureItem(id=item_id, detail=str(exc)))
    return BulkActionResponse(
        ok=len(failed) == 0,
        action=action,
        succeeded=succeeded,
        failed=failed,
    )


class BulkActionsService:
    def bulk_accounts(
        self,
        db: Session,
        *,
        ids: list[int],
        action: str,
        blocked_ids: set[int] | None = None,
        role_id: str | None = None,
        replace_skill: bool = False,
    ) -> BulkActionResponse:
        if action not in ACCOUNT_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        blocked = blocked_ids or set()

        def handle(account_id: int) -> None:
            if action == "delete" and account_id in blocked:
                raise ValueError("Close the open profile browser before deleting this account")
            account = account_service.get(db, account_id)
            if account is None:
                raise ValueError("Account not found")
            if action == "delete":
                account_service.delete(db, account)
            elif action == "disable":
                if account.status not in {
                    AccountStatus.ACTIVE.value,
                    AccountStatus.PENDING_LOGIN.value,
                }:
                    raise ValueError(f"Account cannot be disabled from status {account.status}")
                account_service.update(db, account, status=AccountStatus.DISABLED.value)
            elif action == "enable":
                if account.status != AccountStatus.DISABLED.value:
                    raise ValueError(f"Account cannot be enabled from status {account.status}")
                account_service.update(db, account, status=AccountStatus.PENDING_LOGIN.value)
            elif action == "set_role":
                if not role_id:
                    raise ValueError("role_id is required for set_role")
                account_service.set_role(db, account, role_id=role_id, replace_skill=replace_skill)

        return _run_bulk(action, ids, handle)

    def bulk_variants(
        self,
        db: Session,
        *,
        ids: list[int],
        action: str,
        on_enqueued: Callable[[object], None] | None = None,
    ) -> BulkActionResponse:
        if action not in VARIANT_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")

        def handle(variant_id: int) -> None:
            variant = content_service.get_variant(db, variant_id)
            if variant is None:
                raise ValueError("Variant not found")
            if action == "delete":
                content_service.delete_variant(db, variant)
            elif action == "enqueue":
                extra = json.loads(variant.extra_json or "{}")
                account_id = extra.get("account_id")
                if not account_id:
                    raise ValueError("Variant has no associated account_id")
                if variant.status == "DRAFT":
                    content_service.update_variant(db, variant, status="READY")
                job = job_service.create(
                    db,
                    content_variant_id=variant.id,
                    account_id=int(account_id),
                    scheduled_at=utcnow(),
                )
                if on_enqueued:
                    on_enqueued(job)

        return _run_bulk(action, ids, handle)

    def bulk_llm_models(
        self,
        db: Session,
        *,
        ids: list[int],
        action: str,
        on_deleted: Callable[[int], None] | None = None,
    ) -> BulkActionResponse:
        if action not in LLM_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")

        def handle(model_id: int) -> None:
            row = llm_model_service.get(db, model_id)
            if row is None:
                raise ValueError("LLM model not found")
            if action == "delete":
                llm_model_service.delete(db, row)
                if on_deleted:
                    on_deleted(model_id)
            elif action == "enable":
                llm_model_service.update(db, row, enabled=True)
                if on_deleted:
                    on_deleted(model_id)
            elif action == "disable":
                llm_model_service.update(db, row, enabled=False)
                if on_deleted:
                    on_deleted(model_id)

        return _run_bulk(action, ids, handle)

    def bulk_jobs(self, db: Session, *, ids: list[int], action: str) -> BulkActionResponse:
        if action not in JOB_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")

        def handle(job_id: int) -> None:
            job = job_service.get(db, job_id)
            if job is None:
                raise ValueError("Job not found")
            if action == "cancel":
                job_service.cancel(db, job)
            elif action == "retry":
                job_service.retry(db, job)

        return _run_bulk(action, ids, handle)


bulk_actions_service = BulkActionsService()
