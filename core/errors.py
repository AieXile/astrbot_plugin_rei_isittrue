"""把底层异常转换成绫波丽式的短提示。"""

from __future__ import annotations

_PATTERNS = (
    (
        ("sensitive", "content_filter", "1026", "安全审核"),
        "……图片被安全策略拦住了。换一张试试。",
    ),
    (
        ("rate_limit", "429", "quota", "too many requests"),
        "……太吵了，被限流了。等一会儿再问。",
    ),
    (
        ("timeout", "timed out", "timeouterror"),
        "……没有回应。稍后再试。",
    ),
    (
        ("context_length", "too long", "maximum context", "token"),
        "……内容太长了，做不到。精简一下。",
    ),
    (
        ("401", "invalid api key", "unauthorized"),
        "……钥匙不对。检查一下 API Key。",
    ),
    (
        ("402", "insufficient balance", "余额"),
        "……额度不够了。",
    ),
)


def friendly_error(message: str) -> str:
    lowered = str(message or "").lower()
    for keywords, reply in _PATTERNS:
        if any(keyword in lowered for keyword in keywords):
            return reply
    return "……判断失败。稍后再试。"
