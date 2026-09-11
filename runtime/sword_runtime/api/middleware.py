"""Small ASGI request-body limit without reading or logging secrets."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict


class RequestBodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], max_body_bytes: int) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.lower(): value for key, value in scope.get("headers", ())
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                await self._reject(send, 400, b'{"detail":{"code":"invalid_content_length"}}')
                return
            if content_length < 0:
                await self._reject(send, 400, b'{"detail":{"code":"invalid_content_length"}}')
                return
            if content_length > self.max_body_bytes:
                await self._reject(send, 413, b'{"detail":{"code":"body_too_large"}}')
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._reject(send, 413, b'{"detail":{"code":"body_too_large"}}')

    @staticmethod
    async def _reject(send, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": (
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ),
            }
        )
        await send({"type": "http.response.body", "body": body})
