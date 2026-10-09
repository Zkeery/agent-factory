"""去掉 uvicorn 访问日志里的查询凭证。

SSE 不能自定义请求头，登录令牌仍可通过 query 传递。
本模块在响应开始前改写 scope 中的查询串，并再过滤访问日志，
使 `scripts/ensure-backend.sh` 启动的 uvicorn 默认访问日志不再留下可用令牌。
"""
from __future__ import annotations

import logging
import re

_QUERY_CREDENTIAL = re.compile(r"(?i)(^|(?<=[?&]))(token|api_key)=[^&#\s]*")
_ACCESS_LOGGER = "uvicorn.access"


def redact_credential_text(text: str) -> str:
    return _QUERY_CREDENTIAL.sub(r"\2=***", text)


def redact_query_bytes(raw: bytes) -> bytes:
    text = raw.decode("latin-1")
    redacted = redact_credential_text(text)
    if redacted == text:
        return raw
    return redacted.encode("latin-1")


class AccessCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_credential_text(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact_credential_text(item) if isinstance(item, str) else item for item in args)
        elif isinstance(args, dict):
            record.args = {
                key: redact_credential_text(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        message = record.__dict__.get("message")
        if isinstance(message, str):
            record.message = redact_credential_text(message)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger(_ACCESS_LOGGER)
    _attach(logger)
    for handler in list(logger.handlers):
        _attach(handler)


def _attach(target: logging.Filterer) -> None:
    if any(isinstance(item, AccessCredentialFilter) for item in target.filters):
        return
    target.addFilter(AccessCredentialFilter())


class QueryCredentialRedactionMiddleware:
    """在访问日志读取查询串之前抹掉 token / api_key，不缓冲响应体。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_redacted(message):
            if message.get("type") == "http.response.start":
                raw = scope.get("query_string") or b""
                if raw:
                    scope["query_string"] = redact_query_bytes(raw)
            await send(message)

        await self.app(scope, receive, send_redacted)
