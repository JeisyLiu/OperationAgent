from app.agent.base import AgentAdapter
from app.agent.browser_use_adapter import BrowserUseAdapter
from app.agent.mock_adapter import MockAgentAdapter
from app.config import settings


def create_agent_adapter() -> AgentAdapter:
    adapter = (settings.agent_adapter or "mock").lower().replace("-", "_")
    if adapter in {"browser_use", "browseruse"}:
        return BrowserUseAdapter()
    return MockAgentAdapter()
