from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.base import AgentAdapter
from app.db.models import Account, ContentVariant, PublishJob


@dataclass
class PublishContext:
    db: Session
    job: PublishJob
    account: Account
    variant: ContentVariant
    adapter: AgentAdapter
    execution_dir: Path
    prompt: str


@dataclass
class PublishResult:
    success: bool
    message: str = ""
    error_code: str | None = None
    screenshot_paths: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


class Channel(ABC):
    @abstractmethod
    async def publish(self, ctx: PublishContext) -> PublishResult:
        raise NotImplementedError

    async def read_comments(self, ctx: PublishContext) -> dict:
        raise NotImplementedError("Not implemented in MVP")
