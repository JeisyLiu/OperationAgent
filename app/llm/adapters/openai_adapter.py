from openai import OpenAI

from app.llm.types import ChatResult, TokenUsage
from app.services.llm_model_service import LlmModelConfig


class OpenAIAdapter:
    def __init__(self) -> None:
        self._clients: dict[int, OpenAI] = {}

    def get_client(self, config: LlmModelConfig) -> OpenAI:
        if config.id not in self._clients:
            kwargs: dict = {"api_key": config.api_key or ""}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            self._clients[config.id] = OpenAI(**kwargs)
        return self._clients[config.id]

    def invalidate(self, model_id: int) -> None:
        self._clients.pop(model_id, None)

    def chat(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int = 256,
    ) -> ChatResult:
        if not config.api_key:
            raise ValueError("API key is not configured")
        client = self.get_client(config)
        model = config.model or "gpt-4o-mini"
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=config.timeout_sec,
        )
        content = response.choices[0].message.content
        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        return ChatResult(text=content or "", usage=usage)
