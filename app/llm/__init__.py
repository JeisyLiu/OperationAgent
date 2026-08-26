from app.llm.gateway import gateway
from app.llm.types import BatchItem, BatchResult, ChatResult

__all__ = ["llm", "BatchItem", "BatchResult", "ChatResult"]


class LlmFacade:
    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 256) -> str:
        return gateway.chat(messages, max_tokens=max_tokens, failover=True)

    def chat_with_usage(self, messages: list[dict[str, str]], *, max_tokens: int = 256) -> ChatResult:
        return gateway.chat_with_usage(messages, max_tokens=max_tokens, failover=True)

    def chat_batch(
        self,
        items: list[tuple],
        *,
        max_tokens: int = 256,
        max_workers: int | None = None,
    ) -> list[BatchResult]:
        batch_items = [BatchItem(key=key, messages=messages) for key, messages in items]
        return gateway.chat_batch(batch_items, max_tokens=max_tokens, max_workers=max_workers)

    def chat_single(self, model_id: int, messages: list[dict[str, str]], *, max_tokens: int = 256) -> str:
        return gateway.chat_single(model_id, messages, max_tokens=max_tokens)


llm = LlmFacade()
