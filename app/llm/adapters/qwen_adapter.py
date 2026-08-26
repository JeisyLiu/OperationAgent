from http import HTTPStatus

from dashscope import Generation

from app.llm.types import ChatResult, TokenUsage
from app.services.llm_model_service import LlmModelConfig


class QwenAdapter:
    def chat(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int = 256,
    ) -> ChatResult:
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
        text = ""
        if not choices:
            text = getattr(output, "text", None) or output.get("text")
            if not text:
                raise RuntimeError("DashScope response missing choices")
            text = str(text)
        else:
            first = choices[0]
            message = getattr(first, "message", None) or first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
            else:
                content = getattr(message, "content", None)
            if not content:
                raise RuntimeError("DashScope response missing message content")
            text = str(content)

        usage = None
        usage_obj = getattr(response, "usage", None)
        if usage_obj is not None:
            if isinstance(usage_obj, dict):
                usage = TokenUsage(
                    prompt_tokens=usage_obj.get("input_tokens") or usage_obj.get("prompt_tokens"),
                    completion_tokens=usage_obj.get("output_tokens") or usage_obj.get("completion_tokens"),
                    total_tokens=usage_obj.get("total_tokens"),
                )
            else:
                usage = TokenUsage(
                    prompt_tokens=getattr(usage_obj, "input_tokens", None)
                    or getattr(usage_obj, "prompt_tokens", None),
                    completion_tokens=getattr(usage_obj, "output_tokens", None)
                    or getattr(usage_obj, "completion_tokens", None),
                    total_tokens=getattr(usage_obj, "total_tokens", None),
                )
        return ChatResult(text=text, usage=usage)
