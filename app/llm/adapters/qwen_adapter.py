"""DashScope / Model Studio adapter.

Newer Qwen multimodal models (qwen3.5-*, qwen3.7-*, *-ocr, etc.) and third-party
models on Bailian (Kimi / GLM / …) are not served on the legacy Generation
text-generation endpoint. Calling Generation.call() returns:

  DashScope error 400: url error, please check url！

Default path: OpenAI-compatible endpoint
  https://dashscope.aliyuncs.com/compatible-mode/v1
"""

from __future__ import annotations

from openai import OpenAI

from app.llm.types import ChatResult, TokenUsage
from app.services.llm_model_service import LlmModelConfig

DEFAULT_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenAdapter:
    def __init__(self) -> None:
        self._clients: dict[int, OpenAI] = {}

    def get_client(self, config: LlmModelConfig) -> OpenAI:
        if config.id not in self._clients:
            base_url = (config.base_url or "").strip() or DEFAULT_COMPAT_BASE_URL
            self._clients[config.id] = OpenAI(
                api_key=config.api_key or "",
                base_url=base_url,
            )
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

        # Optional legacy native Generation API (text-only models like qwen-turbo).
        mode = str(config.extra.get("api_mode", "compatible")).lower()
        if mode in {"generation", "native", "dashscope_generation"}:
            return self._chat_generation(messages, config, max_tokens=max_tokens)
        return self._chat_compatible(messages, config, max_tokens=max_tokens)

    def _chat_compatible(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int,
    ) -> ChatResult:
        client = self.get_client(config)
        model = config.model or "qwen-flash"
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                timeout=config.timeout_sec,
            )
        except Exception as exc:
            text = str(exc)
            if "url error" in text.lower() or "InvalidParameter" in text:
                raise RuntimeError(
                    f"DashScope 调用失败（model={model}）：{exc}。"
                    f"请确认模型名在百炼控制台可用；多模态/第三方模型须走兼容模式"
                    f"（默认 {DEFAULT_COMPAT_BASE_URL}），不要用旧 Generation 接口。"
                ) from exc
            raise

        content = response.choices[0].message.content
        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        return ChatResult(text=content or "", usage=usage)

    def _chat_generation(
        self,
        messages: list[dict[str, str]],
        config: LlmModelConfig,
        *,
        max_tokens: int,
    ) -> ChatResult:
        from http import HTTPStatus

        from dashscope import Generation

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
            if "url error" in str(message).lower():
                raise RuntimeError(
                    f"DashScope Generation 不支持模型 {model}（url error）。"
                    f"请把该配置改为默认兼容模式，或换用纯文本旧模型（如 qwen-flash / qwen-plus）。"
                    f"详情: {message}"
                )
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
                    completion_tokens=usage_obj.get("output_tokens")
                    or usage_obj.get("completion_tokens"),
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
