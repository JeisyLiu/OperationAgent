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


def normalize_adapter_name(name: str | None) -> str:
    return (name or "mock").lower().replace("-", "_")


def create_agent_adapter(adapter_name: str | None = None) -> AgentAdapter:
    adapter = normalize_adapter_name(adapter_name or settings.agent_adapter)
    if adapter in {"browser_use", "browseruse"}:
        return BrowserUseAdapter()
    if adapter == "stagehand":
        return StagehandAdapter()
    if adapter == "chrome_devtools":
        return ChromeDevToolsAdapter()
    if adapter == "openclaw":
        return OpenClawAdapter()
    return MockAgentAdapter()


def resolve_adapter_for_platform(platform_id: str) -> AgentAdapter:
    platform = get_platform(platform_id)
    if platform and platform.preferred_adapter:
        pref = normalize_adapter_name(platform.preferred_adapter)
        if pref in KNOWN_ADAPTERS:
            return create_agent_adapter(pref)
    return create_agent_adapter()


def default_adapter_name() -> str:
    return normalize_adapter_name(settings.agent_adapter)


def adapter_name_for_platform(platform_id: str) -> str:
    platform = get_platform(platform_id)
    if platform and platform.preferred_adapter:
        pref = normalize_adapter_name(platform.preferred_adapter)
        if pref in KNOWN_ADAPTERS:
            return pref
    return default_adapter_name()
