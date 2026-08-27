import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agent.base import AgentStatus, StepEvent
from app.constants import StepStatus

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 12

SYSTEM_PROMPT = """You are a browser automation agent. Observe the page snapshot and choose ONE next action.
Respond with JSON only, no markdown:
{
  "action": "click|type|upload|navigate|web_search|done|fail",
  "selector": "css selector when needed",
  "text": "text to type when action=type, or search query when action=web_search",
  "url": "url when action=navigate",
  "message": "reason or final status message"
}
Rules:
- action=web_search runs a web search with text as the query; results appear in prior actions.
- action=done when publish succeeded; message must include status=SUCCESS and evidence.
- action=fail when blocked (login, captcha); message must include status=FAILED and reason.
- Prefer stable selectors: button, a, input, textarea, [role=button].
- One action per step."""


def _parse_action(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("LLM response is not valid JSON") from None
        return json.loads(match.group(0))


def _emit(on_step: Callable[[StepEvent], None] | None, event: StepEvent) -> None:
    if on_step is None:
        return
    try:
        on_step(event)
    except Exception:
        logger.exception("on_step callback failed for step %s phase %s", event.step, event.phase)


def _usage_fields(usage) -> dict[str, int | None]:
    if usage is None:
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


async def observe_page(page) -> str:
    title = await page.title()
    url = page.url
    elements = await page.evaluate(
        """() => {
          const items = [];
          const nodes = document.querySelectorAll(
            'button, a, input, textarea, select, [role=button], [contenteditable=true]'
          );
          let i = 0;
          for (const el of nodes) {
            if (items.length >= 40) break;
            const rect = el.getBoundingClientRect();
            if (rect.width < 2 || rect.height < 2) continue;
            const tag = el.tagName.toLowerCase();
            const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 80);
            const name = el.getAttribute('name') || '';
            const type = el.getAttribute('type') || '';
            const id = el.id ? '#' + el.id : '';
            items.push({i, tag, type, name, id, text});
            i += 1;
          }
          return items;
        }"""
    )
    lines = [f"URL: {url}", f"Title: {title}", "Interactive elements:"]
    for el in elements:
        lines.append(
            f"  [{el['i']}] <{el['tag']}{el['type'] and ' type='+el['type'] or ''}{el['id']}> "
            f"name={el['name']!r} text={el['text']!r}"
        )
    return "\n".join(lines)


async def _execute_action(page, action: dict[str, Any], media_path: str | None) -> str:
    kind = str(action.get("action", "")).lower()
    selector = action.get("selector") or ""
    if kind == "navigate":
        url = action.get("url") or ""
        if not url:
            return "navigate missing url"
        await page.goto(url, wait_until="domcontentloaded")
        return f"navigated to {url}"
    if kind == "click":
        if not selector:
            return "click missing selector"
        await page.click(selector, timeout=15000)
        return f"clicked {selector}"
    if kind == "type":
        if not selector:
            return "type missing selector"
        text = action.get("text") or ""
        await page.fill(selector, text, timeout=15000)
        return f"typed into {selector}"
    if kind == "upload":
        if not media_path:
            return "upload missing media_path"
        if not selector:
            selector = "input[type=file]"
        await page.set_input_files(selector, media_path, timeout=15000)
        return f"uploaded file to {selector}"
    if kind == "web_search":
        from app.services.web_search_service import web_search_service

        query = (action.get("text") or action.get("query") or "").strip()
        if not query:
            return "web_search missing query"
        hits = web_search_service.search(query, max_results=8)
        if not hits:
            return f"web_search returned no results for: {query}"
        lines = [f"web_search ({len(hits)} results) for: {query}"]
        for i, hit in enumerate(hits, start=1):
            lines.append(f"  {i}. {hit.title or '(no title)'} — {hit.url}")
            if hit.snippet:
                lines.append(f"     {hit.snippet[:200]}")
        return "\n".join(lines)
    if kind in {"done", "fail"}:
        return action.get("message") or kind
    return f"unknown action {kind}"


async def run_tool_loop(
    page,
    *,
    task_prompt: str,
    media_path: str | None,
    execution_dir: Path,
    max_steps: int = MAX_TOOL_STEPS,
    llm_chat: Callable[[list[dict[str, str]]], Any] | None = None,
    on_step: Callable[[StepEvent], None] | None = None,
) -> tuple[AgentStatus, str, list[str], dict]:
    from app.llm import llm

    def default_chat(messages: list[dict[str, str]]):
        return llm.chat_with_usage(messages, max_tokens=512)

    chat_fn = llm_chat or default_chat
    screenshots: list[str] = []
    history: list[str] = []

    for step in range(1, max_steps + 1):
        step_started = time.perf_counter()
        observe_started = time.perf_counter()
        snapshot = await observe_page(page)
        observe_ms = int((time.perf_counter() - observe_started) * 1000)

        shot_path = execution_dir / f"step-{step:02d}.png"
        execution_dir.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(shot_path))
            screenshots.append(str(shot_path))
        except Exception:
            logger.warning("Screenshot failed at step %s", step)
            shot_path = None

        _emit(
            on_step,
            StepEvent(
                step=step,
                phase="observe",
                tool_name="observe_page",
                status=StepStatus.SUCCESS.value,
                message="Captured page snapshot",
                duration_ms=observe_ms,
                screenshot_path=str(shot_path) if shot_path else None,
                payload={"snapshot_preview": snapshot[:500]},
            ),
        )

        user_content = (
            f"Task:\n{task_prompt}\n\n"
            f"Media path: {media_path or '(none)'}\n\n"
            f"Page snapshot:\n{snapshot}\n\n"
            f"Prior actions:\n" + ("\n".join(history) if history else "(none)")
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        llm_started = time.perf_counter()
        try:
            raw_result = chat_fn(messages)
            if isinstance(raw_result, str):
                raw = raw_result
                usage = None
            else:
                raw = getattr(raw_result, "text", str(raw_result))
                usage = getattr(raw_result, "usage", None)
            action = _parse_action(raw)
            llm_ms = int((time.perf_counter() - llm_started) * 1000)
            usage_fields = _usage_fields(usage)
            _emit(
                on_step,
                StepEvent(
                    step=step,
                    phase="llm",
                    tool_name="llm_decide",
                    status=StepStatus.SUCCESS.value,
                    message=raw[:300],
                    duration_ms=llm_ms,
                    screenshot_path=str(shot_path) if shot_path else None,
                    payload={"action": action},
                    **usage_fields,
                ),
            )
        except Exception as exc:
            llm_ms = int((time.perf_counter() - llm_started) * 1000)
            _emit(
                on_step,
                StepEvent(
                    step=step,
                    phase="llm",
                    tool_name="llm_decide",
                    status=StepStatus.FAILED.value,
                    message=str(exc),
                    duration_ms=llm_ms,
                    screenshot_path=str(shot_path) if shot_path else None,
                ),
            )
            return AgentStatus.FAILED, f"LLM step failed: {exc}", screenshots, {"error_code": "UNKNOWN"}

        kind = str(action.get("action", "")).lower()
        if kind == "done":
            message = action.get("message") or "status=SUCCESS"
            total_ms = int((time.perf_counter() - step_started) * 1000)
            _emit(
                on_step,
                StepEvent(
                    step=step,
                    phase="done",
                    tool_name=kind,
                    status=StepStatus.SUCCESS.value,
                    message=message,
                    duration_ms=total_ms,
                    screenshot_path=str(shot_path) if shot_path else None,
                    payload={"action": action},
                ),
            )
            return AgentStatus.SUCCESS, message, screenshots, {"status": "SUCCESS", "steps": step}
        if kind == "fail":
            message = action.get("message") or "status=FAILED"
            total_ms = int((time.perf_counter() - step_started) * 1000)
            _emit(
                on_step,
                StepEvent(
                    step=step,
                    phase="fail",
                    tool_name=kind,
                    status=StepStatus.FAILED.value,
                    message=message,
                    duration_ms=total_ms,
                    screenshot_path=str(shot_path) if shot_path else None,
                    payload={"action": action},
                ),
            )
            return AgentStatus.FAILED, message, screenshots, {"status": "FAILED", "steps": step}

        act_started = time.perf_counter()
        try:
            result = await _execute_action(page, action, media_path)
            history.append(f"step {step}: {kind} -> {result}")
            act_status = StepStatus.SUCCESS.value
            act_message = result
        except Exception as exc:
            history.append(f"step {step}: {kind} ERROR -> {exc}")
            logger.warning("Action failed at step %s: %s", step, exc)
            act_status = StepStatus.FAILED.value
            act_message = str(exc)
        act_ms = int((time.perf_counter() - act_started) * 1000)
        _emit(
            on_step,
            StepEvent(
                step=step,
                phase="act",
                tool_name=kind,
                status=act_status,
                message=act_message,
                duration_ms=act_ms,
                screenshot_path=str(shot_path) if shot_path else None,
                payload={
                    "action": action,
                    "selector": action.get("selector"),
                    "text": (action.get("text") or "")[:120],
                },
            ),
        )

    _emit(
        on_step,
        StepEvent(
            step=max_steps,
            phase="fail",
            tool_name="max_steps",
            status=StepStatus.FAILED.value,
            message="Exceeded max tool steps",
        ),
    )
    return (
        AgentStatus.FAILED,
        "status=FAILED: exceeded max tool steps",
        screenshots,
        {"status": "FAILED", "steps": max_steps},
    )
