from dataclasses import dataclass
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class BatchItem:
    key: Any
    messages: list[dict[str, str]]


@dataclass
class BatchResult:
    key: Any
    ok: bool
    text: str | None = None
    error: str | None = None
    model_id: int | None = None
    model_alias: str | None = None
