"""Refuse state-changing requests that a browser sends on another site's behalf.

Removing CORS stopped other websites from reading the API, but not from
writing to it. A page anywhere can still make the owner's browser send a
"simple" cross-site POST (a form, or fetch in no-cors mode), and the browser
attaches whatever credentials it holds for this app, the basic auth in front
of it included. POST /api/scan/clear-index wipes weeks of processing that
way, without the attacker ever seeing a response.

Browsers label every request with where it comes from (Sec-Fetch-Site, and
Origin on POSTs and WebSocket handshakes). The UI's own requests are
same-origin, so anything a browser marks as coming from elsewhere is
refused. Requests without those headers (curl, scripts) are not browser
requests made on someone else's behalf and pass as before.
"""

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return ""


def is_cross_site(scope: Scope) -> bool:
    """True when a browser says this request comes from another site."""
    fetch_site = _header(scope, b"sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in ("same-origin", "none")
    # Older browsers send Origin but no fetch metadata. Compare host names
    # only: nginx forwards Host without the port and the Vite dev proxy
    # rewrites it to the backend's port, while Origin keeps the page's.
    origin = _header(scope, b"origin")
    if origin is None or origin == "null":
        return origin == "null"
    return _hostname(origin) != _hostname(_header(scope, b"host"))


class CrossSiteGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in _SAFE_METHODS:
            if is_cross_site(scope):
                body = json.dumps({"detail": "Cross-site request refused"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        elif scope["type"] == "websocket" and is_cross_site(scope):
            # The pipeline socket streams the error log, file paths included.
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)
