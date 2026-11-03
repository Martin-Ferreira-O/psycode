"""Ciclo de procesos explícitos con exclusión SQL y renovación independiente."""
import signal
import threading
from contextlib import contextmanager
from uuid import uuid4
from django.db import close_old_connections
from django.core.management.base import CommandError
from . import leases

@contextmanager
def singleton(name, ttl=30):
    owner = uuid4()
    if not leases.acquire(name, owner, ttl=ttl):
        raise CommandError("PROCESS_ALREADY_RUNNING")
    stop, done = threading.Event(), threading.Event()
    previous = {}
    def on_signal(*args):
        stop.set()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, on_signal)
    def renew():
        while not done.wait(ttl / 3):
            close_old_connections()
            try:
                if not leases.acquire(name, owner, ttl=ttl):
                    stop.set()
                    return
            except Exception:
                stop.set()
                return
            finally:
                close_old_connections()
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield stop, owner
    finally:
        done.set()
        thread.join(timeout=5)
        leases.release(name, owner)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
