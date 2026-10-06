"""Refuse request bodies that are too large before they are read into memory or disk."""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body

# The largest upload the API accepts is a 50 MB evidence file; this leaves room
# for the multipart envelope around it.
MAX_REQUEST_BYTES = 60 * 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length", b"").decode()
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        too_large = False
        rejected = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started, rejected
            if too_large:
                # The framework turns the read failure into its own error response.
                # Send ours instead, once, and drop the rest.
                if not rejected and not response_started:
                    rejected = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not rejected and not response_started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        megabytes = self.max_bytes // (1024 * 1024)
        body = json.dumps(
            error_body("payload_too_large", f"Uploads must be {megabytes} MB or smaller")
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
