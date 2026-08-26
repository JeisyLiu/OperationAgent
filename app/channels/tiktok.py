import json
import re

from app.agent.base import AgentStatus, AgentTask
from app.channels.base import Channel, PublishContext, PublishResult
from app.constants import AccountStatus, FailureCode, classify_failure
from app.services.content_service import content_service


class TikTokChannel(Channel):
    async def publish(self, ctx: PublishContext) -> PublishResult:
        if ctx.account.status != AccountStatus.ACTIVE.value:
            message = "Account is not ACTIVE. Open profile and mark-active after login."
            return PublishResult(
                success=False,
                message=message,
                error_code=FailureCode.LOGIN_REQUIRED.value,
            )

        if ctx.variant.media_path:
            media = content_service.resolve_file_path(ctx.variant.media_path)
            if not media.exists():
                return PublishResult(
                    success=False,
                    message=f"Media file missing: {ctx.variant.media_path}",
                    error_code=FailureCode.UNKNOWN.value,
                )

        task = AgentTask(
            job_id=ctx.job.id,
            platform=ctx.job.platform,
            profile_path=ctx.job.browser_profile,
            prompt=ctx.prompt,
            media_path=ctx.variant.media_path,
            execution_dir=str(ctx.execution_dir),
            on_step=ctx.on_step,
        )

        result = await ctx.adapter.execute(task)
        error_code = result.data.get("error_code") if result.data else None
        if not error_code and result.status != AgentStatus.SUCCESS:
            error_code = classify_failure(result.message)

        if result.status == AgentStatus.STOPPED:
            return PublishResult(
                success=False,
                message=result.message or "Stopped by user",
                error_code=FailureCode.UNKNOWN.value,
                screenshot_paths=result.screenshot_paths,
                data=result.data,
            )

        if result.status != AgentStatus.SUCCESS:
            message = (result.message or "").strip() or (
                f"[{(result.data or {}).get('adapter') or 'agent'}] 执行失败但未返回错误详情"
            )
            return PublishResult(
                success=False,
                message=message,
                error_code=error_code,
                screenshot_paths=result.screenshot_paths,
                data=result.data,
            )

        verified, verify_message = self._verify(result.message, result.data)
        if not verified:
            return PublishResult(
                success=False,
                message=verify_message,
                error_code=FailureCode.UNKNOWN.value,
                screenshot_paths=result.screenshot_paths,
                data=result.data,
            )

        payload = {
            "message": result.message,
            "verify": verify_message,
            "data": result.data,
            "browser_use_version": result.data.get("browser_use_version"),
            "model": result.data.get("model"),
        }
        return PublishResult(
            success=True,
            message=verify_message,
            screenshot_paths=result.screenshot_paths,
            data=payload,
        )

    def _verify(self, message: str, data: dict) -> tuple[bool, str]:
        combined = f"{message} {json.dumps(data)}".lower()
        if data.get("status") == "SUCCESS":
            return True, "Agent reported SUCCESS"
        if "status=success" in combined or "published successfully" in combined:
            return True, "Publish verified from agent response"
        if re.search(r"tiktok\.com/@[\w.-]+/video/\d+", combined):
            return True, "Publish verified via TikTok video URL"
        if "upload" in combined and "success" in combined:
            return True, "Publish verified via upload success signal"
        return False, "Could not verify publish success from agent response"
