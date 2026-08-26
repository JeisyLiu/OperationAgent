import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.agent.base import AgentStatus

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 12

SYSTEM_PROMPT = """You are a browser automation agent. Observe the page snapshot and choose ONE next action.
Respond with JSON only, no markdown:
{
  "action": "click|type|upload|navigate|done|fail",
  "selector": "css selector when needed",
  "text": "text to type when action=type",
  "url": "url when action=navigate",
  "message": "reason or final status message"
}
Rules:
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
    llm_chat: Callable[[list[dict[str, str]]], str] | None = None,
) -> tuple[AgentStatus, str, list[str], dict]:
    from app.llm import llm

    chat_fn = llm_chat or (lambda messages: llm.chat(messages, max_tokens=512))
    screenshots: list[str] = []
    history: list[str] = []

    for step in range(1, max_steps + 1):
        snapshot = await observe_page(page)
        shot_path = execution_dir / f"step-{step:02d}.png"
        execution_dir.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(shot_path))
            screenshots.append(str(shot_path))
        except Exception:
            logger.warning("Screenshot failed at step %s", step)

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
        try:
            raw = chat_fn(messages)
            action = _parse_action(raw)
        except Exception as exc:
            return AgentStatus.FAILED, f"LLM step failed: {exc}", screenshots, {"error_code": "UNKNOWN"}

        kind = str(action.get("action", "")).lower()
        if kind == "done":
            message = action.get("message") or "status=SUCCESS"
            return AgentStatus.SUCCESS, message, screenshots, {"status": "SUCCESS", "steps": step}
        if kind == "fail":
            message = action.get("message") or "status=FAILED"
            return AgentStatus.FAILED, message, screenshots, {"status": "FAILED", "steps": step}

        try:
            result = await _execute_action(page, action, media_path)
            history.append(f"step {step}: {kind} -> {result}")
        except Exception as exc:
            history.append(f"step {step}: {kind} ERROR -> {exc}")
            logger.warning("Action failed at step %s: %s", step, exc)

    return (
        AgentStatus.FAILED,
        "status=FAILED: exceeded max tool steps",
        screenshots,
        {"status": "FAILED", "steps": max_steps},
    )
