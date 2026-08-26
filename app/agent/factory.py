from app.agent.base import AgentAdapter
from app.agent.browser_use_adapter import BrowserUseAdapter
from app.agent.chrome_devtools_adapter import ChromeDevToolsAdapter
from app.agent.mock_adapter import MockAgentAdapter
from app.agent.openclaw_adapter import OpenClawAdapter
from app.agent.stagehand_adapter import StagehandAdapter
from app.config import settings
from app.platforms import get_platform

KNOWN_ADAPTERS = frozenset(
    {"browser_use", "browseruse", "stagehand", "chrome_devtools", "openclaw", "mock"}
)

# Infra failure degrade chain: browser_use → stagehand → chrome_devtools
FALLBACK_CHAIN = ("browser_use", "stagehand", "chrome_devtools")
FALLBACK_ADAPTER = "chrome_devtools"  # final hop; kept for compatibility


def normalize_adapter_name(name: str | None) -> str:
    name = (name or "mock").lower().replace("-", "_")
    if name == "browseruse":
        return "browser_use"
    return name


def create_agent_adapter(adapter_name: str | None = None) -> AgentAdapter:
    adapter = normalize_adapter_name(adapter_name or settings.agent_adapter)
    if adapter == "browser_use":
        return BrowserUseAdapter()
    if adapter == "stagehand":
        return StagehandAdapter()
    if adapter == "chrome_devtools":
        return ChromeDevToolsAdapter()
    if adapter == "openclaw":
        return OpenClawAdapter()
    return MockAgentAdapter()


def resolve_adapter_for_platform(platform_id: str) -> AgentAdapter:
    return create_agent_adapter(adapter_name_for_platform(platform_id))


def default_adapter_name() -> str:
    return normalize_adapter_name(settings.agent_adapter)


def adapter_name_for_platform(platform_id: str) -> str:
    platform = get_platform(platform_id)
    if platform and platform.preferred_adapter:
        pref = normalize_adapter_name(platform.preferred_adapter)
        if pref in KNOWN_ADAPTERS:
            return pref
    return default_adapter_name()


def next_fallback_adapter(current: str | None) -> str | None:
    """Return the next adapter in the degrade chain, or None if already at the end."""
    name = normalize_adapter_name(current)
    if name == "browseruse":
        name = "browser_use"
    try:
        idx = FALLBACK_CHAIN.index(name)
    except ValueError:
        return None
    if idx + 1 >= len(FALLBACK_CHAIN):
        return None
    return FALLBACK_CHAIN[idx + 1]


def is_infra_failure(message: str | None, error_code: str | None = None) -> bool:
    """Heuristic: failure looks like browser/runtime infra, not login/captcha/content."""
    if error_code in {"LOGIN_REQUIRED", "CAPTCHA_BLOCKED"}:
        return False
    text = (message or "").strip().lower()
    if not text:
        return True
    markers = (
        "notimplementederror",
        "not implemented",
        "create_subprocess",
        "playwright",
        "executable doesn't exist",
        "browsertype.launch",
        "target closed",
        "langchain",
        "no module named",
        "cannot connect to chrome",
        "chrome_devtools",
        "devtools",
        "事件循环",
        "子进程",
        "chromium 未安装",
        "依赖缺失",
        "无详细信息",
        "未知错误",
    )
    return any(m in text for m in markers)


def should_fallback_to_chrome(adapter_name: str | None, message: str | None, error_code: str | None) -> bool:
    """Backward-compatible: True when current adapter can still degrade further on infra failure."""
    return next_fallback_adapter(adapter_name) is not None and is_infra_failure(message, error_code)
