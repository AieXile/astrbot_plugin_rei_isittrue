"""一次事实核查的完整流程编排。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .content import extract_bundle, is_effectively_empty, sanitize_text
from .errors import friendly_error
from .llm import Reviewer
from .planner import Planner
from .prompts import build_user_prompt
from .search import SearchService
from .verdict import Verdict, parse_verdict


@dataclass(frozen=True)
class PipelineResult:
    verdict: Verdict | None = None
    error: str = ""


def now_label() -> str:
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return now.strftime("%Y-%m-%d %H:%M（北京时间）")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def run_check(
    *,
    event: Any,
    settings: Settings,
    context: Any,
    logger: Any,
    strip_keyword: str = "",
) -> PipelineResult:
    bundle = await extract_bundle(event, settings, strip_keyword)
    text = sanitize_text(bundle.text)
    supplement = sanitize_text(bundle.supplement)
    images = bundle.images

    if is_effectively_empty(text, images, supplement):
        return PipelineResult()

    reviewer = Reviewer(settings=settings, context=context, logger=logger)
    notes: list[str] = []
    if bundle.note:
        notes.append(bundle.note)
    if images and not settings.enable_vision:
        notes.append("已关闭图片分析，仅依据文字判断。")

    current = now_label()

    plan = await Planner(
        settings=settings, reviewer=reviewer, logger=logger
    ).plan(text=text, images=images, supplement=supplement, now_label=current)

    search_block = ""
    if settings.enable_web_search and plan.need_search and plan.queries:
        service = SearchService(
            settings=settings, context=context, logger=logger
        )
        blocks: list[str] = []
        for query in plan.queries[: settings.max_search_queries]:
            outcome = await service.search(query, event=event)
            if outcome.text:
                blocks.append(f"### 查询：{query}\n{outcome.text}")
        if blocks:
            search_block = "\n\n".join(blocks)[: settings.max_search_chars]
        else:
            notes.append("联网检索没有可用资料，已回退为图文综合判断。")
    elif settings.enable_web_search and plan.need_search:
        notes.append("规划未给出有效搜索词，已跳过检索。")
    elif settings.enable_web_search:
        notes.append("规划判定无需联网，直接综合判断。")

    prompt = build_user_prompt(
        source=bundle.source,
        text=text,
        image_count=len(images),
        supplement=supplement,
        search_block=search_block,
        notes=notes,
        claim=plan.claim,
        now_label=current,
        max_chars=settings.max_content_chars,
    )

    try:
        outcome = await reviewer.chat(
            prompt_with_images=prompt,
            prompt_without_images=prompt,
            image_urls=images if settings.enable_vision else [],
            system_prompt=settings.system_prompt,
        )
    except Exception as exc:
        logger.exception("事实核查失败：%s", exc)
        return PipelineResult(error=friendly_error(str(exc)))

    verdict = parse_verdict(outcome.text)
    if verdict is None:
        # 模型没按格式输出：给出无法核实，但保留它的解释供用户参考
        verdict = Verdict("unknown", outcome.text.strip()[:200])
    return PipelineResult(verdict=verdict)
