from openai import OpenAI

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
    ) -> str:
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
        return content or ""
