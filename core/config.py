"""插件配置的读取与规范化。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .prompts import DEFAULT_PLAN_PROMPT, DEFAULT_SYSTEM_PROMPT

DEFAULT_TRIGGER_PHRASES = ("真的吗",)
DEFAULT_LABELS = {
    "rei": ("……是真的。", "……是假的。", "……我不知道。"),
    "plain": ("✅ 真的", "❌ 假的", "⚠️ 无法核实"),
}
SEARCH_PROVIDERS = (
    "auto",
    "deepseek",
    "anysearch",
    "tavily",
    "bocha",
    "baidu_ai_search",
    "brave",
    "firecrawl",
    "none",
)
# auto 模式的降级顺序
SEARCH_FALLBACK_ORDER = (
    "deepseek",
    "tavily",
    "anysearch",
    "bocha",
    "baidu_ai_search",
    "brave",
    "firecrawl",
)
REVIEW_BACKENDS = ("astrbot", "deepseek")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        items = []
    result: list[str] = []
    for item in items:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def normalize_phrases(value: Any) -> tuple[str, ...]:
    return _list(value) or DEFAULT_TRIGGER_PHRASES


@dataclass(frozen=True)
class Settings:
    cooldown: int = 10
    trigger_phrases: tuple[str, ...] = DEFAULT_TRIGGER_PHRASES
    listen_suffix: bool = False
    listen_prefix: bool = False
    group_blacklist: frozenset[str] = frozenset()

    review_backend: str = "astrbot"
    provider_id: str = ""
    provider_fallbacks: tuple[str, ...] = ()
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout: int = 60
    enable_vision: bool = True

    enable_web_search: bool = True
    search_provider: str = "auto"
    deepseek_search_key: str = ""
    deepseek_search_count: int = 5
    deepseek_search_content: bool = True
    anysearch_api_key: str = ""
    anysearch_endpoint: str = "https://api.anysearch.com/v1/search"
    anysearch_zone: str = ""
    anysearch_language: str = ""
    max_search_results: int = 5
    max_search_queries: int = 2
    search_timeout: int = 30
    max_content_chars: int = 2500
    max_search_chars: int = 2000
    max_forward_depth: int = 4
    max_forward_nodes: int = 40
    max_forward_images: int = 8

    persona: str = "rei"
    true_label: str = "……是真的。"
    false_label: str = "……是假的。"
    unknown_label: str = "……我不知道。"
    send_verdict_image: bool = True
    true_image_path: str = ""
    false_image_path: str = ""
    system_prompt: str = field(default=DEFAULT_SYSTEM_PROMPT)
    plan_prompt: str = field(default=DEFAULT_PLAN_PROMPT)

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> "Settings":
        config = config or {}
        persona = _text(config.get("persona")).lower()
        if persona not in DEFAULT_LABELS:
            persona = "rei"
        default_true, default_false, default_unknown = DEFAULT_LABELS[persona]
        backend = _text(config.get("review_backend")).lower()
        if backend not in REVIEW_BACKENDS:
            backend = "astrbot"
        search_provider = _text(config.get("search_provider")).lower() or "auto"
        if search_provider not in SEARCH_PROVIDERS:
            search_provider = "auto"

        deepseek_key = _text(config.get("deepseek_api_key"))
        return cls(
            cooldown=_int(config.get("cooldown"), 10, 0, 3600),
            trigger_phrases=normalize_phrases(config.get("trigger_phrases")),
            listen_suffix=_bool(config.get("listen_suffix"), False),
            listen_prefix=_bool(config.get("listen_prefix"), False),
            group_blacklist=frozenset(_list(config.get("group_blacklist"))),
            review_backend=backend,
            provider_id=_text(config.get("provider_id")),
            provider_fallbacks=_list(config.get("provider_fallbacks")),
            deepseek_api_key=deepseek_key,
            deepseek_base_url=(
                _text(config.get("deepseek_base_url"))
                or "https://api.deepseek.com"
            ).rstrip("/"),
            deepseek_model=_text(config.get("deepseek_model"))
            or "deepseek-flash",
            deepseek_timeout=_int(config.get("deepseek_timeout"), 60, 10, 300),
            enable_vision=_bool(config.get("enable_vision"), True),
            enable_web_search=_bool(config.get("enable_web_search"), True),
            search_provider=search_provider,
            deepseek_search_key=_text(config.get("deepseek_search_key"))
            or deepseek_key,
            deepseek_search_count=_int(
                config.get("deepseek_search_count"), 5, 1, 50
            ),
            deepseek_search_content=_bool(
                config.get("deepseek_search_content"), True
            ),
            anysearch_api_key=_text(config.get("anysearch_api_key")),
            anysearch_endpoint=(
                _text(config.get("anysearch_endpoint"))
                or "https://api.anysearch.com/v1/search"
            ),
            anysearch_zone=_text(config.get("anysearch_zone")),
            anysearch_language=_text(config.get("anysearch_language")),
            max_search_results=_int(config.get("max_search_results"), 5, 1, 10),
            max_search_queries=_int(config.get("max_search_queries"), 2, 1, 3),
            search_timeout=_int(config.get("search_timeout"), 30, 5, 180),
            max_content_chars=_int(
                config.get("max_content_chars"), 2500, 200, 20000
            ),
            max_search_chars=_int(
                config.get("max_search_chars"), 2000, 200, 20000
            ),
            max_forward_depth=_int(config.get("max_forward_depth"), 4, 1, 8),
            max_forward_nodes=_int(config.get("max_forward_nodes"), 40, 1, 100),
            max_forward_images=_int(
                config.get("max_forward_images"), 8, 0, 20
            ),
            persona=persona,
            true_label=_text(config.get("true_label")) or default_true,
            false_label=_text(config.get("false_label")) or default_false,
            unknown_label=_text(config.get("unknown_label")) or default_unknown,
            send_verdict_image=_bool(config.get("send_verdict_image"), True),
            true_image_path=_text(config.get("true_image_path")),
            false_image_path=_text(config.get("false_image_path")),
            system_prompt=_text(config.get("system_prompt"))
            or DEFAULT_SYSTEM_PROMPT,
            plan_prompt=_text(config.get("plan_prompt")) or DEFAULT_PLAN_PROMPT,
        )
