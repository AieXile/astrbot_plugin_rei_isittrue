"""AstrBot 插件入口：绫波丽版「是真的吗」。"""

from __future__ import annotations

import time

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.config import Settings
from .core.pipeline import run_check
from .core.render import build_result
from .core.triggers import match_trigger

PLUGIN_NAME = "astrbot_plugin_rei_isittrue"


@register(
    PLUGIN_NAME,
    "AieXile",
    "绫波丽版事实核查：引用消息或 @机器人问「真的吗」，举牌判定真假",
    "v2.0.0",
    "https://github.com/AieXile/astrbot_plugin_rei_isittrue",
)
class ReiIsItTrue(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._cooldowns: dict[str, float] = {}

    async def initialize(self) -> None:
        settings = Settings.from_mapping(self.config)
        logger.info(
            "绫波丽·是真的吗 已加载 | 触发词=%s | 审查=%s | 搜索=%s | 视觉=%s",
            list(settings.trigger_phrases),
            settings.review_backend,
            settings.search_provider if settings.enable_web_search else "off",
            settings.enable_vision,
        )

    async def terminate(self) -> None:
        logger.info("绫波丽·是真的吗 已卸载/重载")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_message(self, event: AstrMessageEvent):
        settings = Settings.from_mapping(self.config)

        group_getter = getattr(event, "get_group_id", None)
        group_id = str(group_getter() or "").strip() if callable(group_getter) else ""
        if group_id and group_id in settings.group_blacklist:
            return

        hit = match_trigger(event, settings)
        if not hit.triggered:
            return

        sender = ""
        getter = getattr(event, "get_sender_id", None)
        if callable(getter):
            sender = str(getter() or "")
        now = time.time()
        last = self._cooldowns.get(sender)
        if (
            sender
            and last is not None
            and settings.cooldown > 0
            and now - last < settings.cooldown
        ):
            remain = int(settings.cooldown - (now - last)) + 1
            event.stop_event()
            yield event.plain_result(f"……等一下。{remain} 秒后再问。")
            return

        if sender:
            self._cooldowns[sender] = now

        result = await run_check(
            event=event,
            settings=settings,
            context=self.context,
            logger=logger,
            strip_keyword=hit.strip,
        )

        event.stop_event()
        if result.error:
            yield event.plain_result(result.error)
            return
        if result.verdict is None:
            yield event.plain_result("……要核查什么？引用一条消息，或直接说出来。")
            return

        chain = build_result(result.verdict, settings)
        chain_result = getattr(event, "chain_result", None)
        if callable(chain_result):
            yield chain_result(chain)
        else:
            from astrbot.api.event import MessageChain

            yield MessageChain(chain=chain)
