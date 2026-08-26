import json
import re

from app.agent.base import AgentStatus, AgentTask
from app.channels.base import Channel, PublishContext, PublishResult
from app.constants import AccountStatus, FailureCode, classify_failure
from app.platforms import get_platform
from app.services.content_service import content_service


class GenericAgentChannel(Channel):
    """Publish via tool-capable AgentAdapter for platforms without a dedicated channel."""

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

        platform = get_platform(ctx.job.platform)
        section = ""
        if ctx.variant.extra_json:
            try:
                extra = json.loads(ctx.variant.extra_json)
                section = extra.get("section") or ""
            except json.JSONDecodeError:
                section = ""

        metadata = {
            "upload_url": platform.upload_url if platform else "",
            "home_url": platform.home_url if platform else "",
            "section": section,
            "channel": "generic",
        }

        task = AgentTask(
            job_id=ctx.job.id,
            platform=ctx.job.platform,
            profile_path=ctx.job.browser_profile,
            prompt=ctx.prompt,
            media_path=ctx.variant.media_path,
            execution_dir=str(ctx.execution_dir),
            metadata=metadata,
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
            return PublishResult(
                success=False,
                message=result.message,
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
            "channel": "generic",
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
        if "publish" in combined and "success" in combined:
            return True, "Publish verified via success signal"
        if re.search(r"https?://[^\s\"']+", combined):
            return True, "Publish verified via URL in agent response"
        return False, "Could not verify publish success from agent response"
