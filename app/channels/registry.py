from app.channels.base import Channel
from app.channels.tiktok import TikTokChannel

_REGISTRY: dict[str, Channel] = {
    "tiktok": TikTokChannel(),
}


def has_channel(channel_id: str) -> bool:
    return channel_id.lower() in _REGISTRY


def get_channel(platform: str) -> Channel:
    channel = _REGISTRY.get(platform.lower())
    if channel is None:
        raise ValueError(f"No channel registered for platform: {platform}")
    return channel
