import threading
from contextlib import contextmanager

from app.llm.adapters.openai_adapter import OpenAIAdapter
from app.llm.adapters.qwen_adapter import QwenAdapter
from app.services.llm_model_service import LlmModelConfig

_openai_adapter = OpenAIAdapter()
_qwen_adapter = QwenAdapter()
_semaphores: dict[int, threading.Semaphore] = {}
_lock = threading.Lock()


def get_adapter(provider: str):
    provider = provider.lower()
    if provider == "openai":
        return _openai_adapter
    if provider == "qwen":
        return _qwen_adapter
    raise ValueError(f"Unsupported provider: {provider}")


def _get_semaphore(config: LlmModelConfig) -> threading.Semaphore:
    with _lock:
        sem = _semaphores.get(config.id)
        if sem is None or sem._value != config.max_concurrency:  # noqa: SLF001
            _semaphores[config.id] = threading.Semaphore(config.max_concurrency)
        return _semaphores[config.id]


@contextmanager
def acquire(config: LlmModelConfig):
    sem = _get_semaphore(config)
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def invalidate_client(model_id: int) -> None:
    _openai_adapter.invalidate(model_id)
    with _lock:
        _semaphores.pop(model_id, None)
