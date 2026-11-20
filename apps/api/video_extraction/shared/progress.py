"""Optional stage counters; never used as evidence or acceptance criteria."""
from contextlib import contextmanager
from contextvars import ContextVar
_reporter = ContextVar("media_progress", default=None)

@contextmanager
def reporting(callback):
    token = _reporter.set(callback)
    try:
        yield
    finally:
        _reporter.reset(token)

def report(stage, completed=0, total=None):
    callback = _reporter.get()
    if callback:
        callback(stage, completed, total)
