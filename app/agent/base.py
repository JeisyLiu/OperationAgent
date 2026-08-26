from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


@dataclass
class StepEvent:
    step: int
    phase: str
    tool_name: str | None = None
    status: str = "RUNNING"
    message: str | None = None
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    screenshot_path: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentTask:
    job_id: int
    platform: str
    profile_path: str
    prompt: str
    media_path: str | None = None
    execution_dir: str | None = None
    metadata: dict = field(default_factory=dict)
    on_step: Callable[[StepEvent], None] | None = None


@dataclass
class AgentResult:
    status: AgentStatus
    message: str = ""
    screenshot_paths: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


class AgentAdapter(ABC):
    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError

    @abstractmethod
    async def pause(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> AgentStatus:
        raise NotImplementedError
