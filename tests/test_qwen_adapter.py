from unittest.mock import MagicMock, patch

from app.llm.adapters.qwen_adapter import DEFAULT_COMPAT_BASE_URL, QwenAdapter
from app.llm.types import ChatResult
from app.services.llm_model_service import LlmModelConfig


def _config(**kwargs) -> LlmModelConfig:
    data = {
        "id": 1,
        "alias": "qwen",
        "provider": "qwen",
        "base_url": None,
        "model": "qwen3.5-plus",
        "api_key": "sk-test",
        "enabled": True,
        "priority": 0,
        "max_concurrency": 4,
        "timeout_sec": 60,
        "extra": {},
    }
    data.update(kwargs)
    return LlmModelConfig(**data)


def test_qwen_default_uses_compatible_mode():
    adapter = QwenAdapter()
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="hello"))]
    mock_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    mock_client.chat.completions.create.return_value = mock_resp

    with patch.object(adapter, "get_client", return_value=mock_client):
        result = adapter.chat([{"role": "user", "content": "hi"}], _config(), max_tokens=16)

    assert isinstance(result, ChatResult)
    assert result.text == "hello"
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "qwen3.5-plus"


def test_qwen_get_client_default_base_url():
    adapter = QwenAdapter()
    with patch("app.llm.adapters.qwen_adapter.OpenAI") as mock_openai:
        adapter.get_client(_config())
        mock_openai.assert_called_once()
        assert mock_openai.call_args.kwargs["base_url"] == DEFAULT_COMPAT_BASE_URL


def test_qwen_generation_url_error_is_clear():
    adapter = QwenAdapter()
    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.message = "url error, please check url！"

    with patch("dashscope.Generation.call", return_value=fake_response):
        try:
            adapter.chat(
                [{"role": "user", "content": "hi"}],
                _config(extra={"api_mode": "generation"}, model="qwen3.5-ocr"),
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "兼容模式" in str(exc) or "不支持" in str(exc)
