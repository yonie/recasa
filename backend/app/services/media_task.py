"""Run blocking media work (decoding photos, RAW and video) in a thread,
with a ceiling on how long it may take.

The files come from the library, so a corrupt or hostile one can make a
decoder spin. A thread cannot be killed; the timeout gives the pipeline its
worker back and fails the photo for that stage. The ceiling is far above
any honest decode on a Raspberry Pi 5 (seconds), so only a hang reaches it.
"""

import asyncio
from collections.abc import Callable
from typing import TypeVar

from backend.app.exceptions import PermanentStageError

T = TypeVar("T")

MEDIA_TIMEOUT_SECONDS = 300.0


class MediaTimeout(PermanentStageError):
    """A decoder ran past MEDIA_TIMEOUT_SECONDS on one file."""


async def run_media_task(fn: Callable[..., T], *args, timeout: float = MEDIA_TIMEOUT_SECONDS) -> T:
    """await fn(*args) in a worker thread; MediaTimeout if it hangs."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)
    except TimeoutError as e:
        raise MediaTimeout(f"timed out after {timeout:.0f}s") from e
