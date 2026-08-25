from http import HTTPStatus

from dashscope import Generation

from app.services.llm_model_service import LlmModelConfig


class QwenAdapter:
    def chat(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int = 256,
    ) -> str:
        if not config.api_key:
            raise ValueError("API key is not configured")
        model = config.model or "qwen-turbo"
        result_format = config.extra.get("result_format", "message")
        response = Generation.call(
            api_key=config.api_key,
            model=model,
            messages=messages,
            result_format=result_format,
            max_tokens=max_tokens,
        )
        if response.status_code != HTTPStatus.OK:
            message = getattr(response, "message", None) or str(response)
            raise RuntimeError(f"DashScope error {response.status_code}: {message}")
        output = response.output
        if output is None:
            raise RuntimeError("DashScope returned empty output")
        choices = getattr(output, "choices", None) or output.get("choices")
        if not choices:
            text = getattr(output, "text", None) or output.get("text")
            if text:
                return str(text)
            raise RuntimeError("DashScope response missing choices")
        first = choices[0]
        message = getattr(first, "message", None) or first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if not content:
            raise RuntimeError("DashScope response missing message content")
        return str(content)
