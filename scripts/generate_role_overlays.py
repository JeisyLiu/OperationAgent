"""Generate skill role overlay JSON files for new platforms and roles."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAYS = ROOT / "app" / "skills" / "overlays"

OLD_ROLES = [
    "product_recommender",
    "product_reviewer",
    "brand_official",
    "developer_official",
    "news_media",
    "educator",
]

NEW_ROLES = [
    "lifestyle_creator",
    "entertainment",
    "community_ops",
    "support_service",
    "affiliate_marketer",
    "recruiter",
    "thought_leader",
    "streamer_live",
]

ALL_PLATFORMS = [
    "_default",
    "rednote",
    "douyin",
    "tiktok",
    "weibo",
    "twitter",
    "bilibili",
    "discord",
    "telegram",
    "linkedin",
    "threads",
]

NEW_PLATFORMS = ["discord", "telegram", "linkedin", "threads"]

ZH_PLATFORMS = {"rednote", "douyin", "weibo", "bilibili"}
EN_PLATFORMS = {"tiktok", "twitter", "discord", "telegram", "linkedin", "threads"}

PLATFORM_SKILL = {
    "_default": {"skill": {}, "persona_suffix": ""},
    "rednote": {
        "skill": {
            "language": "zh-CN",
            "tone": "亲切真实、笔记感",
            "hashtag_style": "2-4 个场景化话题标签",
            "extra_prompt": "标题短小吸睛；正文像给朋友安利。",
        },
        "persona_suffix": "，熟悉小红书笔记结构",
    },
    "douyin": {
        "skill": {
            "language": "zh-CN",
            "tone": "口语化、节奏快",
            "extra_prompt": "前 3 秒钩子；字幕友好短句。",
        },
        "persona_suffix": "，擅长抖音短视频表达",
    },
    "tiktok": {
        "skill": {
            "language": "en",
            "tone": "casual, hook-first",
            "hashtag_style": "3-5 tags mixing reach and niche",
            "extra_prompt": "Strong hook in line one; mobile-scannable caption.",
        },
        "persona_suffix": ", optimized for TikTok",
    },
    "weibo": {
        "skill": {
            "language": "zh-CN",
            "tone": "简短有力、话题感",
            "hashtag_style": "#话题# 1-2 个",
            "extra_prompt": "适合转发讨论；可带话题标签。",
        },
        "persona_suffix": "，熟悉微博话题传播",
    },
    "twitter": {
        "skill": {
            "language": "en",
            "tone": "concise, punchy",
            "hashtag_style": "0-2 relevant hashtags",
            "extra_prompt": "One idea per post; respect character limits.",
        },
        "persona_suffix": ", optimized for X/Twitter",
    },
    "bilibili": {
        "skill": {
            "language": "zh-CN",
            "tone": "UP 主口吻、有梗但不尬",
            "extra_prompt": "可提弹幕互动；分区语境要贴切。",
        },
        "persona_suffix": "，B站社区语感",
    },
    "discord": {
        "skill": {
            "language": "en",
            "tone": "community-friendly, low-hype",
            "extra_prompt": "Write for a channel: bullets ok, no hard-sell spam.",
        },
        "persona_suffix": ", tuned for Discord channels",
    },
    "telegram": {
        "skill": {
            "language": "en",
            "tone": "concise broadcast",
            "extra_prompt": "Channel post: one message, short CTA, optional link.",
        },
        "persona_suffix": ", tuned for Telegram Channel",
    },
    "linkedin": {
        "skill": {
            "language": "en",
            "tone": "professional, minimal emoji",
            "extra_prompt": "Longer caption ok: hook, 2-3 paragraphs, clear takeaway.",
        },
        "persona_suffix": ", tuned for LinkedIn feed",
    },
    "threads": {
        "skill": {
            "language": "en",
            "tone": "casual, conversational",
            "extra_prompt": "Short post under 500 chars; invite replies.",
        },
        "persona_suffix": ", tuned for Threads",
    },
}

ROLE_PLATFORM_TWEAKS: dict[str, dict[str, dict]] = {
    "product_recommender": {
        "discord": {"skill": {"cta": "Ask in thread if you want the link"}, "persona_suffix": "，Discord 社区种草"},
        "linkedin": {"skill": {"tone": "professional recommendation, evidence-based"}, "persona_suffix": "，职场可信推荐"},
    },
    "community_ops": {
        "discord": {"skill": {"tone": "warm moderator, thread-friendly"}, "persona_suffix": "，Discord 社群运营"},
        "linkedin": {"skill": {"tone": "professional community builder"}, "persona_suffix": "，LinkedIn 社群运营"},
    },
    "recruiter": {
        "discord": {"skill": {"tone": "approachable hiring partner"}, "persona_suffix": "，Discord 招聘"},
        "linkedin": {
            "skill": {"tone": "authoritative HR voice", "extra_prompt": "Lead with role impact; structured bullets for requirements."},
            "persona_suffix": "，LinkedIn 招聘主阵地",
        },
    },
    "thought_leader": {
        "linkedin": {
            "skill": {"tone": "executive insight, data-backed"},
            "persona_suffix": "，LinkedIn 思想领袖",
        },
        "threads": {"skill": {"tone": "sharp hot take, invite debate"}, "persona_suffix": "，Threads 观点帖"},
    },
    "support_service": {
        "discord": {"skill": {"structure": ["acknowledge", "steps", "ticket"]}, "persona_suffix": "，Discord 支持频道"},
        "telegram": {"skill": {"tone": "clear FAQ broadcast"}, "persona_suffix": "，Telegram 公告支持"},
    },
    "affiliate_marketer": {
        "telegram": {"skill": {"cta": "Link in channel pin — limited time"}, "persona_suffix": "，Telegram 促销广播"},
        "threads": {"skill": {"tone": "deal alert, casual"}, "persona_suffix": "，Threads 优惠速报"},
    },
    "entertainment": {
        "threads": {"skill": {"tone": "meme-ready, punchy"}, "persona_suffix": "，Threads 娱乐梗"},
        "tiktok": {"skill": {"extra_prompt": "Meme pacing; visual gag setup in caption."}, "persona_suffix": "，TikTok 娱乐向"},
    },
    "streamer_live": {
        "discord": {"skill": {"cta": "Stream starting soon — join voice if you're around"}, "persona_suffix": "，Discord 直播预告"},
        "bilibili": {"skill": {"language": "zh-CN", "cta": "今晚开播，点点预约"}, "persona_suffix": "，B站直播预告"},
    },
}


def _merge(base: dict, tweak: dict | None) -> dict:
    if not tweak:
        return base
    out = {"skill": dict(base.get("skill") or {}), "persona_suffix": base.get("persona_suffix", "")}
    if tweak.get("skill"):
        out["skill"].update(tweak["skill"])
    if tweak.get("persona_suffix"):
        out["persona_suffix"] = tweak["persona_suffix"]
    return out


def write_overlay(role: str, platform: str) -> None:
    base = PLATFORM_SKILL[platform]
    tweak = ROLE_PLATFORM_TWEAKS.get(role, {}).get(platform)
    payload = _merge(base, tweak)
    path = OVERLAYS / role / f"{platform}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for role in OLD_ROLES:
        for platform in NEW_PLATFORMS:
            write_overlay(role, platform)

    for role in NEW_ROLES:
        for platform in ALL_PLATFORMS:
            write_overlay(role, platform)

    print("Overlays generated.")


if __name__ == "__main__":
    main()
