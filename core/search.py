"""联网检索渠道：DeepSeek 搜索 API、AnySearch API、Tavily 与框架内置工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .config import SEARCH_FALLBACK_ORDER, Settings

SessionFactory = Callable[[float], Any]
_MAX_ITEM_CONTENT = 500


def _default_session_factory(timeout: float) -> Any:
    import aiohttp

    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout), trust_env=True
    )


def _short(value: Any, limit: int = _MAX_ITEM_CONTENT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _format_items(
    channel: str,
    items: list[dict[str, Any]],
    limit: int = 5,
) -> str:
    lines: list[str] = [f"## {channel} 搜索结果"]
    count = 0
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = _short(item.get("title") or "无标题", 120)
        url = str(item.get("url") or "")
        detail = (
            item.get("summary")
            or item.get("snippet")
            or item.get("content")
            or ""
        )
        meta: list[str] = []
        if item.get("date"):
            meta.append(str(item["date"])[:10])
        if item.get("site_name"):
            meta.append(str(item["site_name"]))
        line = f"### {title}"
        if meta:
            line += f"（{' · '.join(meta)}）"
        line += f"\n- URL: {url}\n- 内容: {_short(detail)}"
        lines.append(line)
        count += 1
    if count == 0:
        return ""
    return "\n\n".join(lines)


@dataclass(frozen=True)
class SearchOutcome:
    channel: str
    text: str


class SearchService:
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

    # ---------- 对外入口 ----------

    async def search(
        self,
        query: str,
        event: Any = None,
    ) -> SearchOutcome:
        query = (query or "").strip()
        if not query or not self.settings.enable_web_search:
            return SearchOutcome("", "")
        provider = self.settings.search_provider
        if provider == "none":
            return SearchOutcome("", "")

        if provider != "auto":
            text = await self._try(provider, query, event)
            return SearchOutcome(provider if text else "", text)

        for candidate in self._order():
            text = await self._try(candidate, query, event)
            if text:
                return SearchOutcome(candidate, text)
            self.logger.info("搜索渠道 %s 无结果，尝试下一个", candidate)
        return SearchOutcome("", "")

    def _order(self) -> list[str]:
        order: list[str] = []
        try:
            cfg = self.context.get_config(umo=None)
            settings = (cfg or {}).get("provider_settings", {}) or {}
            framework = str(settings.get("websearch_provider", "") or "").lower()
            if framework in SEARCH_FALLBACK_ORDER:
                order.append(framework)
        except Exception:
            pass
        for provider in SEARCH_FALLBACK_ORDER:
            if provider not in order:
                order.append(provider)
        return order

    async def _try(self, provider: str, query: str, event: Any) -> str:
        try:
            if provider == "deepseek":
                return await self._deepseek(query)
            if provider == "anysearch":
                return await self._anysearch(query)
            if provider == "tavily":
                return await self._tavily(query)
            return await self._builtin(provider, query, event)
        except Exception as exc:
            self.logger.warning("搜索渠道 %s 失败：%s", provider, exc)
            return ""

    # ---------- DeepSeek 搜索 ----------

    async def _deepseek(self, query: str) -> str:
        key = self.settings.deepseek_search_key or self.settings.deepseek_api_key
        if not key:
            self.logger.info("未配置 DeepSeek 搜索 Key，跳过")
            return ""
        payload = {
            "query": query[:128],
            "count": self.settings.deepseek_search_count,
            "need_content": self.settings.deepseek_search_content,
        }
        url = f"{self.settings.deepseek_base_url}/v1/tools/search"
        status, body = await self._post(
            url,
            payload,
            {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            raise RuntimeError(f"DeepSeek 搜索 HTTP {status}: {body[:200]}")
        try:
            data = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"DeepSeek 搜索返回非 JSON：{body[:200]}") from exc
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return ""
        return _format_items("DeepSeek", items, self.settings.max_search_results)

    # ---------- AnySearch ----------

    async def _anysearch(self, query: str) -> str:
        if not self.settings.anysearch_api_key:
            self.logger.info("未配置 AnySearch Key，跳过")
            return ""
        payload: dict[str, Any] = {
            "query": query,
            "max_results": min(10, self.settings.max_search_results),
        }
        if self.settings.anysearch_zone:
            payload["zone"] = self.settings.anysearch_zone
        if self.settings.anysearch_language:
            payload["language"] = self.settings.anysearch_language

        status, body = await self._post(
            self.settings.anysearch_endpoint,
            payload,
            {
                "Authorization": f"Bearer {self.settings.anysearch_api_key}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            raise RuntimeError(f"AnySearch HTTP {status}: {body[:200]}")
        try:
            data = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"AnySearch 返回非 JSON：{body[:200]}") from exc

        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(f"AnySearch 业务错误：{data.get('message')}")

        results = None
        if isinstance(data, dict):
            payload_data = data.get("data")
            if isinstance(payload_data, dict):
                results = payload_data.get("results")
            if results is None:
                results = data.get("results")
        if not isinstance(results, list):
            return ""
        return _format_items("AnySearch", results, self.settings.max_search_results)

    # ---------- Tavily ----------

    async def _tavily(self, query: str) -> str:
        keys = self._framework_keys("websearch_tavily_key")
        if not keys:
            return ""
        payload = {"query": query, "max_results": self.settings.max_search_results}
        last_error = ""
        for key in keys:
            status, body = await self._post(
                "https://api.tavily.com/search",
                payload,
                {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            if status == 200:
                try:
                    data = json.loads(body)
                except (TypeError, ValueError):
                    return ""
                items = data.get("results") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    return ""
                return _format_items("Tavily", items, self.settings.max_search_results)
            last_error = f"HTTP {status}: {body[:160]}"
            if status not in {401, 403, 429, 432}:
                break
        raise RuntimeError(last_error or "Tavily 搜索失败")

    # ---------- 框架内置工具 ----------

    async def _builtin(self, provider: str, query: str, event: Any) -> str:
        manager = getattr(self.context, "get_llm_tool_manager", lambda: None)()
        tool = manager.get_func(f"web_search_{provider}") if manager else None
        if tool is None or not getattr(tool, "active", True):
            return ""
        if not hasattr(tool, "call"):
            return ""
        from astrbot.core.astr_agent_context import AstrAgentContext

        agent_context = AstrAgentContext(context=self.context, event=event)
        result = await tool.call(
            agent_context, query=query, max_results=self.settings.max_search_results
        )
        text = str(getattr(result, "result", result) or "").strip()
        if not text or text.startswith("Error:"):
            return ""
        return text

    # ---------- 工具 ----------

    def _framework_keys(self, setting_name: str) -> list[str]:
        try:
            cfg = self.context.get_config(umo=None)
            raw = (cfg or {}).get("provider_settings", {}).get(setting_name, [])
        except Exception:
            return []
        if isinstance(raw, str):
            raw = [raw] if raw.strip() else []
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[int, str]:
        async with self._session_factory(self.settings.search_timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                return int(response.status), await response.text()
