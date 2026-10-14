"""The one piece of the hosted service's browser-pool manager that
homedepot/fetch.py uses: create_scope(), the lock held while an ad-hoc
browser launches. The open-source kit runs no pools, so it is a plain lock."""
import threading
from contextlib import contextmanager

_create_lock = threading.Lock()


@contextmanager
def create_scope():
    with _create_lock:
        yield
