"""模型判定结果解析与绫波丽风格的文本渲染。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings

VERDICTS = ("true", "false", "unknown")

_TOKEN_MAP = {
    "true": "true",
    "false": "false",
    "unknown": "unknown",
    "属实": "true",
    "为真": "true",
    "真": "true",
    "真的": "true",
    "不实": "false",
    "为假": "false",
    "假": "false",
    "假的": "false",
    "无法核实": "unknown",
    "不确定": "unknown",
    "未知": "unknown",
    "布吉岛": "unknown",
}

_STRIP_PREFIX = re.compile(
    r"^[\s#*`>：:\-—\d\.\)\]】]+"
    r"|^(判定|结论|结果|答案|verdict|answer)\s*[:：\-]?\s*",
    flags=re.I,
)
_MD_BOLD = re.compile(r"\*{1,3}|`+|^#{1,6}\s*", flags=re.M)
_EXCLAIM = re.compile(r"[!！]{2,}")
_MAX_EXPLAIN = 200


@dataclass(frozen=True)
class Verdict:
    kind: str
    explanation: str = ""


def _clean_token(token: str) -> str:
    cleaned = token.strip().strip("`\"'“”‘’")
    cleaned = _STRIP_PREFIX.sub("", cleaned).strip()
    return cleaned


def parse_verdict_token(token: str) -> str | None:
    if not token:
        return None
    cleaned = _clean_token(token)
    if not cleaned:
        return None
    match = re.match(
        r"^(true|false|unknown|属实|不实|为真|为假|无法核实|不确定|未知|布吉岛|真|假)"
        r"(?:\s|[（(【\[.,，。!！:：]|$)",
        cleaned,
        flags=re.I,
    )
    if match:
        return _TOKEN_MAP.get(match.group(1).lower())
    compact = re.sub(r"[\s#*（）()【】\[\].,，。!！:：`\"'“”]", "", cleaned)
    return _TOKEN_MAP.get(compact.lower())


def _normalize_explanation(text: str) -> str:
    cleaned = _MD_BOLD.sub("", text or "")
    cleaned = _EXCLAIM.sub("。", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) > _MAX_EXPLAIN:
        cleaned = cleaned[:_MAX_EXPLAIN].rstrip() + "…"
    return cleaned


def parse_verdict(content: str) -> Verdict | None:
    """把模型输出解析为三态判定；失败返回 None。"""
    raw = (content or "").strip()
    if not raw:
        return None
    lines = [line for line in raw.splitlines()]
    if not lines:
        return None

    for index, line in enumerate(lines[:4]):
        kind = parse_verdict_token(line.strip())
        if kind:
            rest = "\n".join(lines[index + 1 :]).strip()
            # 解释首行若又重复了一次判定词，去掉
            if rest:
                first, _, tail = rest.partition("\n")
                if parse_verdict_token(first.strip()) == kind:
                    rest = tail.strip()
            return Verdict(kind, _normalize_explanation(rest))

    lowered = raw.lower()
    if re.search(r"\bfalse\b|不实|为假|是假的|谣言", lowered):
        kind = "false"
    elif re.search(r"\btrue\b|属实|为真|是真的", lowered):
        kind = "true"
    elif re.search(r"\bunknown\b|无法核实|不确定|布吉岛", lowered):
        kind = "unknown"
    else:
        return None
    return Verdict(kind, _normalize_explanation(raw))


def label_for(kind: str, settings: Settings) -> str:
    return {
        "true": settings.true_label,
        "false": settings.false_label,
        "unknown": settings.unknown_label,
    }.get(kind, settings.unknown_label)


def format_text(verdict: Verdict, settings: Settings) -> str:
    label = label_for(verdict.kind, settings)
    if not verdict.explanation:
        return label
    if settings.persona == "rei":
        # 绫波丽式停顿：解释前统一加一个省略号，不重复已有标点
        explanation = verdict.explanation.lstrip("… ")
        return f"{label}\n……{explanation}"
    return f"{label}\n{verdict.explanation}"
