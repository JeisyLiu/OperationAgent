"""Backward-compatible shim; prefer `from app.llm import llm`."""

from app.llm import llm as _llm


def chat(messages: list[dict[str, str]], secrets=None, *, max_tokens: int = 256) -> str:
    return _llm.chat(messages, max_tokens=max_tokens)
