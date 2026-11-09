"""搜索渠道、审查模型与整体流程的自测（mock HTTP）。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import astrbot_plugin_rei_isittrue.core.pipeline as pipeline  # noqa: E402
from astrbot_plugin_rei_isittrue.core.config import Settings  # noqa: E402
from astrbot_plugin_rei_isittrue.core.llm import ChatOutcome, Reviewer  # noqa: E402
from astrbot_plugin_rei_isittrue.core.search import SearchService  # noqa: E402


# ---------- 假 HTTP ----------


class FakeResponse:
    def __init__(self, status: int = 200, body: str = "") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeSession:
    def __init__(self, responses: list[Any], calls: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._calls = calls

    def post(self, url: str, json: Any = None, headers: Any = None) -> FakeResponse:
        self._calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            return FakeResponse(599, "no response")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def make_service(
    responses: list[Any],
    **overrides: Any,
) -> tuple[SearchService, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    config = {
        "enable_web_search": True,
        "search_provider": "auto",
        "deepseek_api_key": "dk",
        "anysearch_api_key": "ak",
    }
    config.update(overrides)
    service = SearchService(
        settings=Settings.from_mapping(config),
        context=FakeContext(),
        logger=FakeLogger(),
        session_factory=lambda timeout: FakeSession(responses, calls),
    )
    return service, calls


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def info(self, message: str, *args: Any) -> None:
        pass

    def warning(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args if args else message)

    def exception(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args if args else message)


class FakeContext:
    def __init__(self) -> None:
        self.providers: dict[str, Any] = {}
        self.default: Any = None

    def get_config(self, umo: str | None = None) -> dict[str, Any]:
        return {}

    def get_provider_by_id(self, provider_id: str) -> Any:
        return self.providers.get(provider_id)

    def get_using_provider(self) -> Any:
        return self.default


class TestDeepSeekSearch(unittest.IsolatedAsyncioTestCase):
    async def test_success(self) -> None:
        payload = {
            "results": [
                {
                    "title": "DeepSeek V4 发布",
                    "url": "https://example.com/v4",
                    "summary": "官方发布了 V4 模型。",
                    "date": "2026-06-01T00:00:00+00:00",
                    "site_name": "Example",
                }
            ]
        }
        service, calls = make_service([FakeResponse(200, json.dumps(payload))])
        outcome = await service.search("DeepSeek V4 发布")
        self.assertEqual(outcome.channel, "deepseek")
        self.assertIn("DeepSeek 搜索结果", outcome.text)
        self.assertIn("DeepSeek V4 发布", outcome.text)
        self.assertIn("https://example.com/v4", outcome.text)
        call = calls[0]
        self.assertEqual(call["url"], "https://api.deepseek.com/v1/tools/search")
        self.assertEqual(call["json"]["count"], 5)
        self.assertTrue(call["json"]["need_content"])
        self.assertEqual(call["headers"]["Authorization"], "Bearer dk")

    async def test_without_key(self) -> None:
        service, calls = make_service(
            [], deepseek_api_key="", anysearch_api_key=""
        )
        outcome = await service.search("hello")
        self.assertEqual(outcome.text, "")
        self.assertEqual(calls, [])

    async def test_401_returns_empty(self) -> None:
        service, _ = make_service(
            [FakeResponse(401, '{"error":"unauthorized"}')],
            search_provider="deepseek",
        )
        outcome = await service.search("hello")
        self.assertEqual(outcome.text, "")
        self.assertEqual(outcome.channel, "")


class TestAnySearch(unittest.IsolatedAsyncioTestCase):
    async def test_success(self) -> None:
        payload = {
            "code": 0,
            "message": "success",
            "data": {
                "results": [
                    {
                        "title": "Go 1.26",
                        "url": "https://go.dev/doc/go1.26",
                        "snippet": "Release notes",
                    }
                ]
            },
        }
        service, calls = make_service(
            [FakeResponse(200, json.dumps(payload))],
            search_provider="anysearch",
        )
        outcome = await service.search("Go 1.26 release")
        self.assertEqual(outcome.channel, "anysearch")
        self.assertIn("AnySearch 搜索结果", outcome.text)
        self.assertEqual(
            calls[0]["url"], "https://api.anysearch.com/v1/search"
        )
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer ak")

    async def test_business_error(self) -> None:
        payload = {"code": -1, "message": "Query is required."}
        service, _ = make_service(
            [FakeResponse(400, json.dumps(payload))],
            search_provider="anysearch",
        )
        outcome = await service.search("x")
        self.assertEqual(outcome.text, "")

    async def test_no_key(self) -> None:
        service, calls = make_service(
            [], search_provider="anysearch", anysearch_api_key=""
        )
        outcome = await service.search("x")
        self.assertEqual(outcome.text, "")
        self.assertEqual(calls, [])


class TestAutoFallback(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_anysearch(self) -> None:
        payload = {
            "code": 0,
            "data": {"results": [{"title": "结果", "url": "https://x"}]},
        }
        service, calls = make_service(
            [
                FakeResponse(401, "{}"),  # deepseek 失败
                FakeResponse(200, json.dumps(payload)),  # anysearch 成功
            ]
        )
        outcome = await service.search("query")
        self.assertEqual(outcome.channel, "anysearch")
        self.assertIn("结果", outcome.text)
        self.assertEqual(len(calls), 2)

    async def test_disabled(self) -> None:
        service, calls = make_service([], enable_web_search=False)
        outcome = await service.search("query")
        self.assertEqual(outcome.text, "")
        self.assertEqual(calls, [])

    async def test_none_provider(self) -> None:
        service, calls = make_service([], search_provider="none")
        outcome = await service.search("query")
        self.assertEqual(outcome.text, "")
        self.assertEqual(calls, [])


# ---------- 审查模型 ----------


class StubProvider:
    def __init__(self, provider_id: str, texts: list[str], fail_vision: bool = False):
        self.provider_config = {"id": provider_id}
        self._texts = list(texts)
        self._fail_vision = fail_vision
        self.calls: list[dict[str, Any]] = []

    async def text_chat(self, *, prompt: str, image_urls: Any, system_prompt: str):
        self.calls.append({"images": list(image_urls or [])})
        if image_urls and self._fail_vision:
            raise RuntimeError("image not supported 400")
        if not self._texts:
            raise RuntimeError("provider unavailable")
        text = self._texts.pop(0)
        return type("Resp", (), {"completion_text": text})()


def make_reviewer(
    responses: list[Any],
    **overrides: Any,
) -> tuple[Reviewer, FakeContext, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    context = FakeContext()
    config = {"deepseek_api_key": "dk"}
    config.update(overrides)
    reviewer = Reviewer(
        settings=Settings.from_mapping(config),
        context=context,
        logger=FakeLogger(),
        session_factory=lambda timeout: FakeSession(responses, calls),
    )
    return reviewer, context, calls


class TestReviewer(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_backend(self) -> None:
        body = {
            "choices": [
                {"message": {"content": "false\n这是谣言。"}}
            ]
        }
        reviewer, _, calls = make_reviewer(
            [FakeResponse(200, json.dumps(body))], review_backend="deepseek"
        )
        outcome = await reviewer.chat(
            prompt_with_images="p",
            prompt_without_images="p",
            image_urls=["https://img"],
            system_prompt="s",
        )
        self.assertEqual(outcome.label, "deepseek")
        self.assertIn("false", outcome.text)
        self.assertEqual(
            calls[0]["url"], "https://api.deepseek.com/chat/completions"
        )
        self.assertEqual(calls[0]["json"]["model"], "deepseek-flash")

    async def test_deepseek_failure_falls_back_to_provider(self) -> None:
        provider = StubProvider("go/deepseek", ["true\n官方已发布。"])
        reviewer, context, _ = make_reviewer(
            [FakeResponse(401, "{}")], review_backend="deepseek"
        )
        context.default = provider
        outcome = await reviewer.chat(
            prompt_with_images="p",
            prompt_without_images="p",
            image_urls=[],
            system_prompt="s",
        )
        self.assertEqual(outcome.label, "go/deepseek")
        self.assertIn("true", outcome.text)

    async def test_vision_degrade(self) -> None:
        provider = StubProvider("p1", ["unknown\n看不清。"], fail_vision=True)
        reviewer, context, _ = make_reviewer([], review_backend="astrbot")
        context.default = provider
        outcome = await reviewer.chat(
            prompt_with_images="with image",
            prompt_without_images="without image",
            image_urls=["https://img"],
            system_prompt="s",
        )
        self.assertTrue(outcome.degraded)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0]["images"], ["https://img"])
        self.assertEqual(provider.calls[1]["images"], [])

    async def test_provider_chain_order(self) -> None:
        primary = StubProvider("primary", [])
        fallback = StubProvider("fallback", ["true\nok"])
        reviewer, context, _ = make_reviewer(
            [],
            review_backend="astrbot",
            provider_id="primary",
            provider_fallbacks=["fallback"],
        )
        context.providers = {"primary": primary, "fallback": fallback}
        outcome = await reviewer.chat(
            prompt_with_images="p",
            prompt_without_images="p",
            image_urls=[],
            system_prompt="s",
        )
        self.assertEqual(outcome.label, "fallback")

    async def test_no_provider_raises(self) -> None:
        reviewer, _, _ = make_reviewer([], review_backend="astrbot")
        with self.assertRaises(RuntimeError):
            await reviewer.chat(
                prompt_with_images="p",
                prompt_without_images="p",
                image_urls=[],
                system_prompt="s",
            )


# ---------- 整体流程 ----------


class Plain:
    type = "Plain"

    def __init__(self, text: str) -> None:
        self.text = text


class Reply:
    type = "Reply"

    def __init__(self, text: str) -> None:
        self.message_str = text
        self.chain = [Plain(text)]


class FakeEvent:
    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages

    def get_messages(self) -> list[Any]:
        return self._messages

    def get_self_id(self) -> str:
        return "999"


class ScriptedReviewer:
    def __init__(self, responses: list[str], error: Exception | None = None) -> None:
        self._responses = list(responses)
        self._error = error
        self.calls = 0

    async def chat(self, **kwargs: Any) -> ChatOutcome:
        self.calls += 1
        if self._error:
            raise self._error
        text = self._responses.pop(0) if self._responses else "unknown\n无输出"
        return ChatOutcome(text, "stub")


class TestPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._original = pipeline.Reviewer

    async def asyncTearDown(self) -> None:
        pipeline.Reviewer = self._original

    async def test_true_flow(self) -> None:
        pipeline.Reviewer = lambda **kwargs: ScriptedReviewer(
            ["CLAIM: 地球是圆的\nSEARCH: none\nNEED_SEARCH: no\nNOTE:", "true\n这是常识。"]
        )
        result = await pipeline.run_check(
            event=FakeEvent([Reply("地球是圆的"), Plain("真的吗")]),
            settings=Settings.from_mapping({"enable_web_search": False}),
            context=FakeContext(),
            logger=FakeLogger(),
        )
        self.assertIsNotNone(result.verdict)
        self.assertEqual(result.verdict.kind, "true")

    async def test_error_is_friendly(self) -> None:
        pipeline.Reviewer = lambda **kwargs: ScriptedReviewer(
            [], error=RuntimeError("request timeout")
        )
        result = await pipeline.run_check(
            event=FakeEvent([Reply("某件事")]),
            settings=Settings.from_mapping({"enable_web_search": False}),
            context=FakeContext(),
            logger=FakeLogger(),
        )
        self.assertIsNone(result.verdict)
        self.assertIn("没有回应", result.error)

    async def test_empty_content_silent(self) -> None:
        pipeline.Reviewer = lambda **kwargs: ScriptedReviewer([])
        result = await pipeline.run_check(
            event=FakeEvent([Reply(""), Plain("真的吗")]),
            settings=Settings.from_mapping({"enable_web_search": False}),
            context=FakeContext(),
            logger=FakeLogger(),
        )
        self.assertIsNone(result.verdict)
        self.assertEqual(result.error, "")

    async def test_malformed_output_becomes_unknown(self) -> None:
        pipeline.Reviewer = lambda **kwargs: ScriptedReviewer(
            ["CLAIM: x\nSEARCH: none\nNEED_SEARCH: no\nNOTE:", "我也说不准"]
        )
        result = await pipeline.run_check(
            event=FakeEvent([Reply("某件事")]),
            settings=Settings.from_mapping({"enable_web_search": False}),
            context=FakeContext(),
            logger=FakeLogger(),
        )
        self.assertEqual(result.verdict.kind, "unknown")
        self.assertIn("说不准", result.verdict.explanation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
