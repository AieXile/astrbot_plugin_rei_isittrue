"""检索规划：抽取核心主张 + 生成搜索词。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .prompts import build_plan_prompt

_USELESS_QUERY = re.compile(
    r"^(none|无|没有|图片|截图|如图|看图|段子|梗|meme|-|无搜索)$", re.I
)
_JOKE_MARK = re.compile(
    r"段子|玩笑|幽默|梗图|梗|meme|调侃|恶搞|虚构|搞笑|二创|网络流传", re.I
)
_FACT_MARK = re.compile(
    r"开源|闭源|发布|上线|版本|价格|调价|模型|公司|官方|法律|政策|法案|"
    r"公告|通报|论文|销量|营收|融资|收购|停课|放假|去世|结婚|离婚|夺冠",
)
_FIELD_RE = {
    "claim": re.compile(r"^\s*CLAIM\s*[:：]\s*(.*)$", re.I),
    "search": re.compile(r"^\s*SEARCH\s*[:：]\s*(.*)$", re.I),
    "need": re.compile(r"^\s*NEED_SEARCH\s*[:：]\s*(.*)$", re.I),
    "note": re.compile(r"^\s*NOTE\s*[:：]\s*(.*)$", re.I),
}


@dataclass(frozen=True)
class Plan:
    claim: str = ""
    queries: tuple[str, ...] = ()
    need_search: bool = True
    note: str = ""
    fallback: bool = False
    rescued: bool = False


def _is_useless(query: str) -> bool:
    text = (query or "").strip()
    if len(text) < 2 or _USELESS_QUERY.match(text):
        return True
    # 只剩括号/空白等占位符号，没有实际检索价值
    return bool(re.fullmatch(r"[\[\]【】()（）\s]+", text))


def _split_queries(raw: str) -> list[str]:
    items = re.split(r"[|｜、;；\n]+", raw or "")
    result: list[str] = []
    for item in items:
        text = item.strip().strip("\"'“”")
        text = re.sub(r"^(搜索词|query)\s*[:：]\s*", "", text, flags=re.I)
        if text and not _is_useless(text) and text not in result:
            result.append(text[:80])
    return result[:3]


def parse_plan(raw: str, max_queries: int) -> Plan | None:
    if not raw:
        return None
    values = {"claim": "", "search": "", "need": "", "note": ""}
    for line in raw.splitlines():
        for key, pattern in _FIELD_RE.items():
            match = pattern.match(line)
            if match:
                values[key] = match.group(1).strip()
                break

    if not any(values.values()):
        return None

    claim = re.sub(r"\s+", " ", values["claim"]).strip()
    queries = tuple(_split_queries(values["search"])[:max_queries])
    need_raw = values["need"].lower()
    need_search = need_raw.startswith("y") or need_raw.startswith("是")
    if not values["need"]:
        need_search = bool(queries)
    note = re.sub(r"\s+", " ", values["note"]).strip()[:200]
    return Plan(
        claim=claim[:300],
        queries=queries,
        need_search=need_search,
        note=note,
    )


def fallback_plan(text: str, max_queries: int) -> Plan:
    claim = re.sub(r"\s+", " ", (text or "").strip())[:300]
    if not claim:
        return Plan(need_search=False, fallback=True)
    query = re.sub(r"\s+", " ", claim)[:60]
    return Plan(
        claim=claim,
        queries=(query,) if query else (),
        need_search=True,
        fallback=True,
    )


def rescue_plan(
    plan: Plan,
    *,
    text: str,
    image_count: int,
    max_queries: int,
) -> Plan:
    """规划器把可核内容判成「不用搜」时，做一次保守救援。"""
    if plan.need_search:
        return plan
    blob = f"{text} {plan.claim} {plan.note}"
    if not blob.strip() and not image_count:
        return plan
    if _JOKE_MARK.search(blob) or _FACT_MARK.search(blob):
        rescued = fallback_plan(text or plan.claim, max_queries)
        return Plan(
            claim=plan.claim or rescued.claim,
            queries=rescued.queries,
            need_search=bool(rescued.queries),
            note=plan.note,
            fallback=plan.fallback,
            rescued=True,
        )
    return plan


class Planner:
    def __init__(self, *, settings: Settings, reviewer: Any, logger: Any) -> None:
        self.settings = settings
        self.reviewer = reviewer
        self.logger = logger

    async def plan(
        self,
        *,
        text: str,
        images: list[str],
        supplement: str,
        now_label: str,
    ) -> Plan:
        prompt = build_plan_prompt(
            text=text,
            image_count=len(images),
            supplement=supplement,
            now_label=now_label,
            max_chars=self.settings.max_content_chars,
        )
        raw = ""
        try:
            outcome = await self.reviewer.chat(
                prompt_with_images=prompt,
                prompt_without_images=prompt,
                image_urls=images if self.settings.enable_vision else [],
                system_prompt=self.settings.plan_prompt,
            )
            raw = outcome.text
        except Exception as exc:
            self.logger.warning("检索规划失败，使用兜底规划：%s", exc)

        plan = parse_plan(raw, self.settings.max_search_queries)
        if plan is None:
            plan = fallback_plan(text, self.settings.max_search_queries)
        return rescue_plan(
            plan,
            text=text,
            image_count=len(images),
            max_queries=self.settings.max_search_queries,
        )
