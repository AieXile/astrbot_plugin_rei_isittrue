"""把判定结果渲染成消息链（绫波丽举牌图片 + 文字）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .verdict import Verdict, format_text

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGES = {
    "true": PLUGIN_ROOT / "assets" / "verdict_true.png",
    "false": PLUGIN_ROOT / "assets" / "verdict_false.png",
}


def image_path_for(kind: str, settings: Settings) -> Path | None:
    """返回判定图片路径；unknown 或未启用时返回 None。"""
    if not settings.send_verdict_image:
        return None
    if kind == "true":
        custom = settings.true_image_path
    elif kind == "false":
        custom = settings.false_image_path
    else:
        return None

    if custom:
        path = Path(custom).expanduser()
        if path.is_file():
            return path
    default = DEFAULT_IMAGES.get(kind)
    return default if default and default.is_file() else None


def build_result(
    verdict: Verdict,
    settings: Settings,
    *,
    image_component: Any = None,
    plain_component: Any = None,
) -> list[Any]:
    """构造消息链。

    image_component / plain_component 由调用方注入（测试时可传假的），
    生产环境默认使用 astrbot 的 Image / Plain。
    """
    text = format_text(verdict, settings)
    if plain_component is None or image_component is None:
        from astrbot.api.message_components import Image, Plain

        plain_component = plain_component or Plain
        image_component = image_component or Image

    chain: list[Any] = []
    path = image_path_for(verdict.kind, settings)
    if path is not None:
        chain.append(image_component.fromFileSystem(str(path)))
    chain.append(plain_component(text))
    return chain
