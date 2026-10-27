"""Bounded, process-local sign-in throttling for the local prototype."""

import time
from collections import OrderedDict
from threading import Lock

from fastapi import HTTPException

_attempts = OrderedDict()
_lock = Lock()
WINDOW = 300
MAX_FAILURES = 8


def check_attempt(key):
    with _lock:
        entries = [t for t in _attempts.get(key, []) if t > time.monotonic() - WINDOW]
        if len(entries) >= MAX_FAILURES:
            raise HTTPException(
                429,
                "Too many failed sign-in attempts. Wait five minutes and try again.",
            )


def failed_attempt(key):
    with _lock:
        now = time.monotonic()
        _attempts[key] = [t for t in _attempts.get(key, []) if t > now - WINDOW] + [now]
        _attempts.move_to_end(key)
        while len(_attempts) > 1024:
            _attempts.popitem(last=False)


def clear_attempts(key):
    with _lock:
        _attempts.pop(key, None)
