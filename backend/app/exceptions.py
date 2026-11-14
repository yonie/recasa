"""Shared exception types."""


class PermanentStageError(Exception):
    """A pipeline stage failed in a way that retrying cannot fix.

    Raised by services when the photo file itself is the problem (corrupted,
    truncated, unreadable). The worker persists these as StageFailure records
    so scans stop re-queueing the photo for that stage. Transient errors
    (network, service down) must NOT use this: raise a normal exception so
    the photo is retried on a later scan.
    """
