"""Ciclo de procesos explícitos con exclusión SQL y renovación independiente."""
import signal
import threading
import time
from contextlib import contextmanager
from uuid import uuid4
from django.db import OperationalError, close_old_connections
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
    lease_lost = threading.Event()

    def renew():
        deadline = time.monotonic() + ttl
        delay = ttl / 3
        while not done.wait(delay):
            close_old_connections()
            try:
                if not leases.acquire(name, owner, ttl=ttl, renew_only=True):
                    lease_lost.set()
                    stop.set()
                    return
            except OperationalError:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    delay = min(1, remaining)
                    continue
                lease_lost.set()
                stop.set()
                return
            except Exception:
                lease_lost.set()
                stop.set()
                return
            else:
                deadline = time.monotonic() + ttl
                delay = ttl / 3
            finally:
                close_old_connections()
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield stop, owner
        if lease_lost.is_set():
            raise CommandError("PROCESS_LEASE_LOST")
    finally:
        done.set()
        thread.join(timeout=5)
        try:
            leases.release(name, owner)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
