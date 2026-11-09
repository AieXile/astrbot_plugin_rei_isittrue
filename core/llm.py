"""审查模型调用：AstrBot Provider 回退链 + DeepSeek 直连。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings

SessionFactory = Callable[[float], Any]


def _default_session_factory(timeout: float) -> Any:
    import aiohttp

    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout), trust_env=True
    )


@dataclass(frozen=True)
class ChatOutcome:
    text: str
    label: str
    degraded: bool = False


class Reviewer:
    """按配置调用模型，返回首行 true/false/unknown 的原始文本。"""

    def __init__(
        self,
        *,
        settings: Settings,
        context: Any,
        logger: Any,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.settings = settings
        self.context = context
        self.logger = logger
        self._session_factory = session_factory or _default_session_factory

    # ---------- 对外 ----------

    async def chat(
        self,
        *,
        prompt_with_images: str,
        prompt_without_images: str,
        image_urls: list[str],
        system_prompt: str,
    ) -> ChatOutcome:
        errors: list[str] = []

        if self.settings.review_backend == "deepseek":
            try:
                text = await self._deepseek_chat(
                    prompt_without_images, system_prompt
                )
                if text:
                    return ChatOutcome(text, "deepseek", bool(image_urls))
            except Exception as exc:
                errors.append(f"deepseek: {exc}")
                self.logger.warning("DeepSeek 审查失败：%s", exc)

        providers = self._providers()
        for provider in providers:
            label = self._label(provider)
            if image_urls and self.settings.enable_vision:
                try:
                    response = await provider.text_chat(
                        prompt=prompt_with_images,
                        image_urls=image_urls,
                        system_prompt=system_prompt,
                    )
                    text = str(getattr(response, "completion_text", "") or "").strip()
                    if text:
                        return ChatOutcome(text, label, False)
                except Exception as exc:
                    errors.append(f"{label}: {exc}")
                    self.logger.warning("%s 带图调用失败：%s", label, exc)
            try:
                response = await provider.text_chat(
                    prompt=prompt_without_images,
                    image_urls=[],
                    system_prompt=system_prompt,
                )
                text = str(getattr(response, "completion_text", "") or "").strip()
                if text:
                    return ChatOutcome(text, label, bool(image_urls))
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                self.logger.warning("%s 调用失败：%s", label, exc)

        if errors:
            raise RuntimeError("；".join(errors))
        raise RuntimeError("没有可用的审查模型")

    # ---------- AstrBot Provider ----------

    def _providers(self) -> list[Any]:
        order: list[Any] = []
        seen: set[str] = set()

        def add(provider: Any) -> None:
            if provider is None:
                return
            label = self._label(provider)
            if label in seen:
                return
            seen.add(label)
            order.append(provider)

        getter = getattr(self.context, "get_provider_by_id", None)
        if self.settings.provider_id and callable(getter):
            add(getter(self.settings.provider_id))
        for fallback in self.settings.provider_fallbacks:
            if callable(getter):
                add(getter(fallback))
        using = getattr(self.context, "get_using_provider", None)
        if callable(using):
            add(using())
        return order

    @staticmethod
    def _label(provider: Any) -> str:
        try:
            return str(provider.provider_config.get("id", "")) or type(provider).__name__
        except Exception:
            return type(provider).__name__

    # ---------- DeepSeek 直连 ----------

    async def _deepseek_chat(self, prompt: str, system_prompt: str) -> str:
        key = self.settings.deepseek_api_key
        if not key:
            raise RuntimeError("未配置 DeepSeek API Key")
        url = f"{self.settings.deepseek_base_url}/chat/completions"
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        async with self._session_factory(self.settings.deepseek_timeout) as session:
            async with session.post(
                url, json=payload, headers=headers
            ) as response:
                status = int(response.status)
                body = await response.text()
        if status != 200:
            raise RuntimeError(f"DeepSeek HTTP {status}: {body[:200]}")
        try:
            data = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"DeepSeek 返回非 JSON：{body[:200]}") from exc
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "").strip()
