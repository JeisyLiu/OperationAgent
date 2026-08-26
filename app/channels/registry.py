from app.channels.base import Channel
from app.channels.generic import GenericAgentChannel
from app.channels.tiktok import TikTokChannel

_REGISTRY: dict[str, Channel] = {
    "tiktok": TikTokChannel(),
}

_GENERIC = GenericAgentChannel()


def has_channel(channel_id: str) -> bool:
    return channel_id.lower() in _REGISTRY


def get_channel(platform: str) -> Channel:
    channel = _REGISTRY.get(platform.lower())
    if channel is not None:
        return channel
    return _GENERIC
