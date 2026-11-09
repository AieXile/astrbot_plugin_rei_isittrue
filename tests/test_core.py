"""配置、触发、判定、渲染、内容提取、规划的自测。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_rei_isittrue.core.config import Settings  # noqa: E402
from astrbot_plugin_rei_isittrue.core.content import extract_bundle  # noqa: E402
from astrbot_plugin_rei_isittrue.core.planner import (  # noqa: E402
    fallback_plan,
    parse_plan,
    rescue_plan,
)
from astrbot_plugin_rei_isittrue.core.render import (  # noqa: E402
    build_result,
    image_path_for,
)
from astrbot_plugin_rei_isittrue.core.triggers import (  # noqa: E402
    match_trigger,
    phrase_hit,
    strip_triggers,
)
from astrbot_plugin_rei_isittrue.core.verdict import (  # noqa: E402
    Verdict,
    format_text,
    parse_verdict,
)


# ---------- 假组件 / 事件 ----------


class Plain:
    type = "Plain"

    def __init__(self, text: str) -> None:
        self.text = text


class Image:
    type = "Image"

    def __init__(self, url: str = "") -> None:
        self.url = url
        self.file = ""


class At:
    type = "At"

    def __init__(self, qq: str) -> None:
        self.qq = qq


class Reply:
    type = "Reply"

    def __init__(self, text: str = "", images: list[str] | None = None) -> None:
        self.message_str = text
        self.chain = [Plain(text)] if text else []
        for url in images or []:
            self.chain.append(Image(url))


class Node:
    type = "Node"

    def __init__(self, content: list[Any]) -> None:
        self.content = content


class Nodes:
    type = "Nodes"

    def __init__(self, nodes: list[Any]) -> None:
        self.nodes = nodes


class FakeEvent:
    def __init__(self, messages: list[Any], self_id: str = "999") -> None:
        self._messages = messages
        self._self_id = self_id
        self.stopped = False

    def get_messages(self) -> list[Any]:
        return self._messages

    def get_self_id(self) -> str:
        return self._self_id


class TestSettings(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = Settings.from_mapping({})
        self.assertEqual(settings.trigger_phrases, ("真的吗",))
        self.assertEqual(settings.review_backend, "astrbot")
        self.assertEqual(settings.search_provider, "auto")
        self.assertTrue(settings.enable_web_search)
        self.assertEqual(settings.persona, "rei")
        self.assertEqual(settings.true_label, "……是真的。")

    def test_normalization(self) -> None:
        settings = Settings.from_mapping(
            {
                "review_backend": "DEEPSEEK",
                "search_provider": "none",
                "deepseek_api_key": " k ",
                "cooldown": -5,
                "max_search_queries": 99,
                "persona": "plain",
                "trigger_phrases": ["求证", "真的吗", "求证"],
            }
        )
        self.assertEqual(settings.review_backend, "deepseek")
        self.assertEqual(settings.search_provider, "none")
        self.assertEqual(settings.deepseek_api_key, "k")
        self.assertEqual(settings.deepseek_search_key, "k")
        self.assertEqual(settings.cooldown, 0)
        self.assertEqual(settings.max_search_queries, 3)
        self.assertEqual(settings.true_label, "✅ 真的")
        self.assertEqual(settings.trigger_phrases, ("求证", "真的吗"))

    def test_invalid_enum_falls_back(self) -> None:
        settings = Settings.from_mapping(
            {"review_backend": "openai", "search_provider": "unknown"}
        )
        self.assertEqual(settings.review_backend, "astrbot")
        self.assertEqual(settings.search_provider, "auto")


class TestTriggers(unittest.TestCase):
    def test_at_bot_with_phrase(self) -> None:
        event = FakeEvent([At("999"), Plain(" 地球是圆的真的吗")])
        hit = match_trigger(event, Settings.from_mapping({}))
        self.assertTrue(hit.triggered)

    def test_reply_with_phrase(self) -> None:
        event = FakeEvent([Reply("地球是圆的"), Plain("真的吗")])
        hit = match_trigger(event, Settings.from_mapping({}))
        self.assertTrue(hit.triggered)

    def test_at_bot_without_phrase_ignored(self) -> None:
        event = FakeEvent([At("999"), Plain(" 今天金价多少")])
        hit = match_trigger(event, Settings.from_mapping({}))
        self.assertFalse(hit.triggered)

    def test_suffix_listen(self) -> None:
        settings = Settings.from_mapping({"listen_suffix": True})
        event = FakeEvent([Plain("地球是平的真的吗？")])
        hit = match_trigger(event, settings)
        self.assertTrue(hit.triggered)
        self.assertEqual(hit.strip, "真的吗？")

    def test_prefix_listen(self) -> None:
        settings = Settings.from_mapping({"listen_prefix": True})
        event = FakeEvent([Plain("真的吗 地球是平的")])
        hit = match_trigger(event, settings)
        self.assertTrue(hit.triggered)
        self.assertEqual(hit.strip, "真的吗")

    def test_english_boundary(self) -> None:
        self.assertTrue(phrase_hit("this is true", "true"))
        self.assertFalse(phrase_hit("trust me", "true"))

    def test_strip_triggers(self) -> None:
        self.assertEqual(
            strip_triggers("真的吗 地球是平的", ("真的吗",)), "地球是平的"
        )
        self.assertEqual(
            strip_triggers("地球是平的真的吗？", ("真的吗",), "真的吗？"),
            "地球是平的",
        )


class TestVerdict(unittest.TestCase):
    def test_parse_three_states(self) -> None:
        self.assertEqual(parse_verdict("true\n因为资料支持").kind, "true")
        self.assertEqual(parse_verdict("false\n资料否定").kind, "false")
        self.assertEqual(parse_verdict("unknown\n资料不足").kind, "unknown")

    def test_parse_with_wrapping(self) -> None:
        verdict = parse_verdict("**结论**：false\n这是谣言。")
        self.assertEqual(verdict.kind, "false")
        self.assertIn("谣言", verdict.explanation)

    def test_parse_chinese_token(self) -> None:
        self.assertEqual(parse_verdict("属实\n官方公告已发布").kind, "true")
        self.assertEqual(parse_verdict("不实\n无此公告").kind, "false")

    def test_parse_duplicate_token_line_removed(self) -> None:
        verdict = parse_verdict("true\ntrue\n解释内容")
        self.assertEqual(verdict.explanation, "解释内容")

    def test_parse_invalid(self) -> None:
        self.assertIsNone(parse_verdict("我不太确定呢"))

    def test_format_rei(self) -> None:
        text = format_text(Verdict("true", "官方已发布"), Settings.from_mapping({}))
        self.assertTrue(text.startswith("……是真的。"))
        self.assertIn("……官方已发布", text)

    def test_format_plain(self) -> None:
        settings = Settings.from_mapping({"persona": "plain"})
        text = format_text(Verdict("unknown", "资料不足"), settings)
        self.assertTrue(text.startswith("⚠️ 无法核实"))

    def test_explanation_trimmed(self) -> None:
        verdict = parse_verdict("false\n" + "字" * 500)
        self.assertLessEqual(len(verdict.explanation), 201)


class FakeImageComponent:
    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def fromFileSystem(cls, path: str) -> "FakeImageComponent":
        return cls(path)


class FakePlainComponent:
    def __init__(self, text: str) -> None:
        self.text = text


class TestRender(unittest.TestCase):
    def test_true_image_exists(self) -> None:
        settings = Settings.from_mapping({})
        path = image_path_for("true", settings)
        self.assertIsNotNone(path)
        self.assertTrue(path and path.is_file())

    def test_false_image_exists(self) -> None:
        path = image_path_for("false", Settings.from_mapping({}))
        self.assertIsNotNone(path)
        self.assertTrue(path and path.is_file())

    def test_unknown_has_no_image(self) -> None:
        self.assertIsNone(image_path_for("unknown", Settings.from_mapping({})))

    def test_image_disabled(self) -> None:
        settings = Settings.from_mapping({"send_verdict_image": False})
        self.assertIsNone(image_path_for("true", settings))

    def test_chain_order(self) -> None:
        settings = Settings.from_mapping({})
        chain = build_result(
            Verdict("true", "官方公告已发布"),
            settings,
            image_component=FakeImageComponent,
            plain_component=FakePlainComponent,
        )
        self.assertEqual(len(chain), 2)
        self.assertIsInstance(chain[0], FakeImageComponent)
        self.assertIn("是真的", chain[1].text)


class TestContent(unittest.IsolatedAsyncioTestCase):
    async def test_quoted_text_and_images(self) -> None:
        event = FakeEvent(
            [Reply("地球是圆的", ["https://img/1.png"]), Plain("真的吗")]
        )
        bundle = await extract_bundle(event, Settings.from_mapping({}))
        self.assertEqual(bundle.source, "引用消息")
        self.assertIn("地球是圆的", bundle.text)
        self.assertEqual(bundle.images, ["https://img/1.png"])
        self.assertEqual(bundle.supplement, "")

    async def test_current_message(self) -> None:
        event = FakeEvent([Plain("地球是平的真的吗")])
        bundle = await extract_bundle(
            event, Settings.from_mapping({}), "真的吗"
        )
        self.assertEqual(bundle.source, "当前消息")
        self.assertEqual(bundle.text, "地球是平的")

    async def test_forward_nodes(self) -> None:
        event = FakeEvent(
            [
                Nodes(
                    [
                        Node([Plain("第一条消息"), Image("https://img/a.png")]),
                        Node([Plain("第二条消息")]),
                    ]
                )
            ]
        )
        bundle = await extract_bundle(event, Settings.from_mapping({}))
        self.assertEqual(bundle.source, "合并转发")
        self.assertIn("第一条消息", bundle.text)
        self.assertIn("第二条消息", bundle.text)
        self.assertEqual(bundle.images, ["https://img/a.png"])

    async def test_forward_node_budget(self) -> None:
        event = FakeEvent(
            [Nodes([Node([Plain("x" * 100)]) for _ in range(50)])]
        )
        settings = Settings.from_mapping(
            {"max_forward_nodes": 3, "max_content_chars": 10000}
        )
        bundle = await extract_bundle(event, settings)
        self.assertIn("截断", bundle.note)


class TestPlanner(unittest.TestCase):
    def test_parse_plan(self) -> None:
        plan = parse_plan(
            "CLAIM: 某模型已开源\nSEARCH: 某模型 开源 | 官方公告\n"
            "NEED_SEARCH: yes\nNOTE: 技术事实",
            2,
        )
        self.assertTrue(plan.need_search)
        self.assertEqual(plan.queries, ("某模型 开源", "官方公告"))
        self.assertIn("开源", plan.claim)

    def test_parse_no_search(self) -> None:
        plan = parse_plan(
            "CLAIM:\nSEARCH: none\nNEED_SEARCH: no\nNOTE: 纯口味", 2
        )
        self.assertFalse(plan.need_search)
        self.assertEqual(plan.queries, ())

    def test_parse_invalid(self) -> None:
        self.assertIsNone(parse_plan("随便说说", 2))

    def test_fallback_plan(self) -> None:
        plan = fallback_plan("某产品今天涨价了", 2)
        self.assertTrue(plan.fallback)
        self.assertTrue(plan.need_search)
        self.assertEqual(plan.queries, ("某产品今天涨价了",))

    def test_rescue_plan(self) -> None:
        plan = parse_plan(
            "CLAIM:\nSEARCH: none\nNEED_SEARCH: no\nNOTE: 段子", 2
        )
        rescued = rescue_plan(plan, text="这个模型已经开源了", image_count=0, max_queries=2)
        self.assertTrue(rescued.rescued)
        self.assertTrue(rescued.need_search)


if __name__ == "__main__":
    unittest.main(verbosity=2)
