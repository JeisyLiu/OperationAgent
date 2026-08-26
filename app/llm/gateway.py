import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.db.session import SessionLocal
from app.llm import pool
from app.llm.types import BatchItem, BatchResult, ChatResult, TokenUsage
from app.services.llm_model_service import LlmModelConfig, llm_model_service

logger = logging.getLogger(__name__)


class LlmGateway:
    def _load_candidates(self, model_id: int | None) -> list[LlmModelConfig]:
        db = SessionLocal()
        try:
            if model_id is not None:
                cfg = llm_model_service.get_config(db, model_id)
                if cfg is None:
                    raise ValueError(f"LLM model {model_id} not found")
                if not cfg.enabled:
                    raise ValueError(f"LLM model {model_id} is disabled")
                return [cfg]
            configs = llm_model_service.list_enabled_configs(db)
            if not configs:
                raise ValueError("No enabled LLM model configured")
            return configs
        finally:
            db.close()

    def _chat_with_config(
        self,
        config: LlmModelConfig,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
    ) -> ChatResult:
        if not config.api_key:
            raise ValueError(f"Model '{config.alias}' has no API key")
        adapter = pool.get_adapter(config.provider)
        with pool.acquire(config):
            return adapter.chat(messages, config, max_tokens=max_tokens)

    def chat_with_usage(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: int | None = None,
        max_tokens: int = 256,
        failover: bool = True,
    ) -> ChatResult:
        if model_id is not None:
            config = self._load_candidates(model_id)[0]
            return self._chat_with_config(config, messages, max_tokens=max_tokens)

        configs = self._load_candidates(None)
        if not failover:
            return self._chat_with_config(configs[0], messages, max_tokens=max_tokens)

        last_error: Exception | None = None
        for index, config in enumerate(configs):
            try:
                result = self._chat_with_config(config, messages, max_tokens=max_tokens)
                if index > 0:
                    logger.warning(
                        "LLM failover succeeded with model id=%s alias=%s provider=%s",
                        config.id,
                        config.alias,
                        config.provider,
                    )
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed for id=%s alias=%s provider=%s model=%s: %s",
                    config.id,
                    config.alias,
                    config.provider,
                    config.model,
                    exc,
                )
                continue
        raise RuntimeError(f"All LLM models failed: {last_error}")

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: int | None = None,
        max_tokens: int = 256,
        failover: bool = True,
    ) -> str:
        return self.chat_with_usage(
            messages,
            model_id=model_id,
            max_tokens=max_tokens,
            failover=failover,
        ).text

    def chat_single(
        self,
        model_id: int,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 256,
    ) -> str:
        return self.chat(messages, model_id=model_id, max_tokens=max_tokens, failover=False)

    def chat_batch(
        self,
        items: list[BatchItem],
        *,
        max_tokens: int = 256,
        max_workers: int | None = None,
    ) -> list[BatchResult]:
        if not items:
            return []
        workers = max_workers or min(8, len(items))
        results: list[BatchResult] = []

        def _run(item: BatchItem) -> BatchResult:
            try:
                text = self.chat(item.messages, max_tokens=max_tokens, failover=True)
                return BatchResult(key=item.key, ok=True, text=text)
            except Exception as exc:
                return BatchResult(key=item.key, ok=False, error=str(exc))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_run, item): item for item in items}
            for future in as_completed(futures):
                results.append(future.result())
        return results


gateway = LlmGateway()
