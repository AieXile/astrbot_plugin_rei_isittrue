"""消息链组件的轻量识别工具（不依赖具体组件类，便于单测）。"""

from __future__ import annotations

from typing import Any, Iterable

# 图片占位符：不能当作有效待核文本或搜索词
IMAGE_PLACEHOLDER_TOKENS = (
    "[Image]",
    "[image]",
    "[图片]",
    "【图片】",
    "[图像]",
    "【圖像】",
    "[img]",
    "[IMG]",
)


def component_name(component: Any) -> str:
    kind = getattr(component, "type", "")
    value = getattr(kind, "value", kind)
    if value:
        return str(value).lower()
    return type(component).__name__.lower()


def is_component(component: Any, expected: str) -> bool:
    target = expected.lower()
    return component_name(component) == target or (
        type(component).__name__.lower() == target
    )


def plain_text(component: Any) -> str:
    return str(getattr(component, "text", "") or "")


def image_source(component: Any) -> str:
    for attr in ("url", "file", "path", "file_"):
        value = getattr(component, attr, "")
        if value:
            return str(value)
    return ""


def collect_plain(components: Iterable[Any]) -> str:
    return "".join(plain_text(c) for c in components if is_component(c, "Plain"))


def collect_images(components: Iterable[Any]) -> list[str]:
    images: list[str] = []
    for component in components:
        if not is_component(component, "Image"):
            continue
        source = image_source(component)
        if source and source not in images:
            images.append(source)
    return images


def is_at_bot(components: Iterable[Any], self_id: str) -> bool:
    target = str(self_id or "").strip()
    if not target:
        return False
    for component in components:
        if not is_component(component, "At"):
            continue
        if str(getattr(component, "qq", "")).strip() == target:
            return True
    return False


def has_reply(components: Iterable[Any]) -> bool:
    return any(is_component(c, "Reply") for c in components)


def strip_image_placeholders(text: str) -> str:
    cleaned = text or ""
    for token in IMAGE_PLACEHOLDER_TOKENS:
        cleaned = cleaned.replace(token, " ")
    return " ".join(cleaned.split())
