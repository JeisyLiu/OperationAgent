from app.channels.base import Channel
from app.channels.tiktok import TikTokChannel

_REGISTRY: dict[str, Channel] = {
    "tiktok": TikTokChannel(),
}


def get_channel(platform: str) -> Channel:
    channel = _REGISTRY.get(platform.lower())
    if channel is None:
        raise ValueError(f"No channel registered for platform: {platform}")
    return channel
