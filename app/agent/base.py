from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class AgentStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


@dataclass
class AgentTask:
    job_id: int
    platform: str
    profile_path: str
    prompt: str
    media_path: str | None = None
    execution_dir: str | None = None
    metadata: dict = field(default_factory=dict)


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
