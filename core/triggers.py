"""触发判定：@机器人 / 引用 / 前后缀监听。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .chain import collect_plain, has_reply, is_at_bot
from .config import Settings


@dataclass(frozen=True)
class TriggerHit:
    triggered: bool = False
    strip: str = ""


def phrase_hit(text: str, phrase: str) -> bool:
    """中文用包含匹配；英文/数字按词边界，避免 true 命中 trust。"""
    if not text or not phrase:
        return False
    if phrase == text:
        return True
    if text.startswith(phrase) or text.endswith(phrase):
        return True
    if re.fullmatch(r"[A-Za-z0-9_+\-]+", phrase):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])"
        return re.search(pattern, text) is not None
    return phrase in text


def _messages(event: Any) -> list[Any]:
    getter = getattr(event, "get_messages", None)
    return list(getter() if callable(getter) else [])


def _self_id(event: Any) -> str:
    getter = getattr(event, "get_self_id", None)
    return str(getter() if callable(getter) else "")


def match_trigger(event: Any, settings: Settings) -> TriggerHit:
    components = _messages(event)
    plain = collect_plain(components).strip()
    phrases = sorted(settings.trigger_phrases, key=len, reverse=True)
    has_keyword = any(phrase_hit(plain, p) for p in phrases)

    # 1) @机器人 + 触发词（始终生效）
    if has_keyword and is_at_bot(components, _self_id(event)):
        return TriggerHit(True, "")

    # 2) 引用 + 触发词（始终生效）
    if has_keyword and has_reply(components):
        return TriggerHit(True, "")

    if not plain:
        return TriggerHit()

    # 3) 结尾监听
    if settings.listen_suffix:
        for phrase in phrases:
            for key in (f"{phrase}？", f"{phrase}?", phrase):
                if plain.endswith(key) and phrase_hit(plain, phrase):
                    return TriggerHit(True, key)

    # 4) 开头监听
    if settings.listen_prefix:
        for phrase in phrases:
            if plain.startswith(phrase) and phrase_hit(plain, phrase):
                return TriggerHit(True, phrase)

    return TriggerHit()


def strip_triggers(text: str, phrases: tuple[str, ...], strip_keyword: str = "") -> str:
    """去掉触发词，留下真正的待核内容。"""
    cleaned = (text or "").strip()
    if strip_keyword:
        cleaned = cleaned.replace(strip_keyword, " ")
    for phrase in sorted(phrases, key=len, reverse=True):
        for variant in (f"{phrase}？", f"{phrase}?", phrase):
            cleaned = cleaned.replace(variant, " ")
    return " ".join(cleaned.split())
