"""Request body size limits.

nginx in front accepts bodies of any size (client_max_body_size 0) and the
multipart parser spools uploads to disk before a handler sees them, so a
size check inside a handler comes too late. This ASGI middleware refuses an
oversized body up front when Content-Length announces it, and stops reading
one that grows past the limit while streaming in.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Every JSON body the API takes (a name, two ids, a list of ids) is tiny.
DEFAULT_MAX_BODY = 1024 * 1024

# A user-data export carries every faceprint of the named people: about
# 2.7 kB each, so a fully named 50k-face library is ~140 MB. Parsing costs
# roughly the file size again in memory, which the Pi can take at this cap.
MAX_IMPORT_BODY = 256 * 1024 * 1024

BODY_LIMITS = {"/api/user-data/import": MAX_IMPORT_BODY}


class BodyTooLarge(Exception):
    """Raised from receive() once a streamed body passes the limit."""


async def _send_413(send: Send) -> None:
    body = json.dumps({"detail": "Request body too large"}).encode()
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


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = BODY_LIMITS.get(scope["path"], DEFAULT_MAX_BODY)
        for name, value in scope["headers"]:
            if name == b"content-length":
                if not value.isdigit() or int(value) > limit:
                    await _send_413(send)
                    return
                break

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            # Reached only if nothing turned the error into a response yet
            # (FastAPI reports a body it could not read as a 400 itself).
            if not started:
                await _send_413(send)
