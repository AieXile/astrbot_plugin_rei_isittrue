"""从消息事件中提取待核内容：引用 / 图文 / 合并转发。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .chain import (
    collect_images,
    collect_plain,
    image_source,
    is_at_bot,
    is_component,
    plain_text,
    strip_image_placeholders,
)
from .config import Settings
from .triggers import strip_triggers


@dataclass
class Bundle:
    source: str = "当前消息"
    text: str = ""
    images: list[str] = field(default_factory=list)
    supplement: str = ""
    note: str = ""


@dataclass
class _Budget:
    max_depth: int
    max_nodes: int
    max_images: int
    max_chars: int
    nodes: int = 0
    images: int = 0
    chars: int = 0
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    def allow_depth(self, depth: int) -> bool:
        if depth > self.max_depth:
            self.truncated = True
            return False
        return True

    def take_node(self) -> bool:
        if self.nodes >= self.max_nodes:
            self.truncated = True
            return False
        self.nodes += 1
        return True

    def take_text(self, text: str) -> str:
        remaining = self.max_chars - self.chars
        if remaining <= 0:
            self.truncated = True
            return ""
        clipped = text[:remaining]
        self.chars += len(clipped)
        if len(clipped) < len(text):
            self.truncated = True
        return clipped

    def take_images(self, urls: Iterable[str]) -> list[str]:
        result: list[str] = []
        for url in urls:
            if self.images >= self.max_images:
                self.truncated = True
                break
            self.images += 1
            result.append(url)
        return result

    def summary(self) -> str:
        if not self.truncated:
            return ""
        return "合并转发内容过多，已按上限截断。"


def _components(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    chain = getattr(value, "chain", None) or getattr(value, "message", None)
    return list(chain or [])


def _parse_node(node: Any, budget: _Budget, depth: int) -> tuple[str, list[str]]:
    content = getattr(node, "content", None) or getattr(node, "message", None) or []
    return _parse_components(_components(content), budget, depth)


def _parse_node_list(nodes: Any, budget: _Budget, depth: int) -> tuple[str, list[str]]:
    items = getattr(nodes, "nodes", None) or _components(nodes)
    texts: list[str] = []
    images: list[str] = []
    for item in items:
        if not budget.take_node():
            break
        if is_component(item, "Node"):
            text, imgs = _parse_node(item, budget, depth)
        else:
            text, imgs = _parse_components([item], budget, depth)
        if text:
            texts.append(text)
        images.extend(imgs)
    return "\n".join(texts).strip(), images


def _parse_components(
    components: list[Any],
    budget: _Budget,
    depth: int,
) -> tuple[str, list[str]]:
    texts: list[str] = []
    images: list[str] = []
    for component in components:
        if is_component(component, "Plain"):
            text = budget.take_text(plain_text(component))
            if text.strip():
                texts.append(text.strip())
        elif is_component(component, "Image"):
            source = image_source(component)
            if source:
                images.extend(budget.take_images([source]))
        elif is_component(component, "Node"):
            if budget.take_node():
                text, imgs = _parse_node(component, budget, depth + 1)
                if text:
                    texts.append(text)
                images.extend(imgs)
        elif is_component(component, "Nodes"):
            text, imgs = _parse_node_list(component, budget, depth + 1)
            if text:
                texts.append(text)
            images.extend(imgs)
        elif is_component(component, "Reply"):
            text, imgs = _parse_components(
                _components(component), budget, depth
            )
            if text:
                texts.append(text)
            images.extend(imgs)
    return "\n".join(texts).strip(), images


async def _remote_forward(
    event: Any,
    forward_id: str,
    budget: _Budget,
    depth: int,
) -> tuple[str, list[str]]:
    """尽力展开 OneBot 远程合并转发；失败返回空。"""
    if not forward_id or not budget.allow_depth(depth):
        return "", []
    client = getattr(event, "bot", None)
    if client is None or not hasattr(client, "call_action"):
        return "", []
    try:
        payload = await client.call_action("get_forward_msg", id=forward_id)
    except Exception:
        budget.notes.append("合并转发未能展开。")
        return "", []
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return "", []
    texts: list[str] = []
    images: list[str] = []
    for message in messages:
        if not budget.take_node():
            break
        if isinstance(message, dict):
            sender = message.get("sender") or {}
            name = str(sender.get("nickname") or sender.get("card") or "").strip()
            content = message.get("content") or message.get("message") or ""
            if isinstance(content, str):
                text = budget.take_text(content)
                texts.append(f"{name}: {text}".strip(": ").strip())
                continue
        text, imgs = _parse_components(_components(message), budget, depth + 1)
        if text:
            texts.append(text)
        images.extend(imgs)
    return "\n".join(texts).strip(), images


async def _quoted_content(
    event: Any,
    reply: Any,
    budget: _Budget,
) -> tuple[str, list[str]]:
    """优先使用框架的引用解析，失败时回退到 Reply.chain。"""
    text = ""
    images: list[str] = []
    try:
        from astrbot.core.utils.quoted_message_parser import (
            extract_quoted_message_images,
            extract_quoted_message_text,
        )

        text = await extract_quoted_message_text(event, reply) or ""
        images = list(await extract_quoted_message_images(event, reply) or [])
    except Exception:
        text, images = "", []

    if not text and not images:
        text, images = _parse_components(_components(reply), budget, 1)
    if not text and not images:
        text = str(
            getattr(reply, "message_str", "")
            or getattr(reply, "text", "")
            or ""
        ).strip()
    return text, images


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


async def extract_bundle(
    event: Any,
    settings: Settings,
    strip_keyword: str = "",
) -> Bundle:
    getter = getattr(event, "get_messages", None)
    chain = list(getter() if callable(getter) else [])
    self_id = ""
    id_getter = getattr(event, "get_self_id", None)
    if callable(id_getter):
        self_id = str(id_getter() or "")

    current_chain = [
        c for c in chain if not (is_at_bot([c], self_id))
    ]
    current_text = strip_triggers(
        collect_plain(current_chain), settings.trigger_phrases, strip_keyword
    )
    current_images = collect_images(current_chain)

    budget = _Budget(
        max_depth=settings.max_forward_depth,
        max_nodes=settings.max_forward_nodes,
        max_images=settings.max_forward_images,
        max_chars=settings.max_content_chars,
    )

    # 1) 合并转发（Node / Nodes / Forward）
    forward_texts: list[str] = []
    forward_images: list[str] = []
    for component in chain:
        if is_component(component, "Nodes"):
            text, images = _parse_node_list(component, budget, 1)
            forward_texts.append(text)
            forward_images.extend(images)
        elif is_component(component, "Node"):
            if budget.take_node():
                text, images = _parse_node(component, budget, 1)
                forward_texts.append(text)
                forward_images.extend(images)
        elif is_component(component, "Forward"):
            forward_id = str(getattr(component, "id", "") or "").strip()
            text, images = await _remote_forward(event, forward_id, budget, 1)
            forward_texts.append(text)
            forward_images.extend(images)

    forward_text = "\n".join(t for t in forward_texts if t).strip()
    if forward_text or forward_images:
        return Bundle(
            source="合并转发",
            text=forward_text,
            images=_dedupe([*forward_images, *current_images]),
            supplement=current_text,
            note=budget.summary(),
        )

    # 2) 引用消息
    for component in chain:
        if not is_component(component, "Reply"):
            continue
        text, images = await _quoted_content(event, component, budget)
        if text or images:
            return Bundle(
                source="引用消息",
                text=text,
                images=_dedupe([*images, *current_images]),
                supplement=current_text,
                note=budget.summary(),
            )

    # 3) 当前消息
    return Bundle(
        source="当前消息",
        text=current_text,
        images=current_images,
        note=budget.summary(),
    )


def sanitize_text(text: str) -> str:
    return strip_image_placeholders(text)


def is_effectively_empty(text: str, images: list[str], supplement: str) -> bool:
    return not sanitize_text(text) and not images and not sanitize_text(supplement)
