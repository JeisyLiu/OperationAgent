from abc import ABC, abstractmethod
from pathlib import Path


class ComputerRuntime(ABC):
    @abstractmethod
    async def open_profile(self, profile_path: Path, url: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def screenshot(self, output_path: Path) -> Path:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
