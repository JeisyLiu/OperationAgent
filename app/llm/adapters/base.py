from typing import Protocol

from app.services.llm_model_service import LlmModelConfig


class LlmAdapter(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int = 256,
    ) -> str: ...
