"""Primitivas de concurrencia compartidas por el pipeline y la API."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class SingleFlight:
    """Un candado por clave: cálculos idénticos simultáneos se hacen una sola vez."""

    def __init__(self) -> None:
        self._locks: dict[object, threading.Lock] = {}
        self._guard = threading.Lock()

    def run(self, key: object, lookup: Callable[[], T | None], compute: Callable[[], T]) -> T:
        """``lookup`` (caché) primero; si no hay, calcula bajo el candado de ``key``."""
        hit = lookup()
        if hit is not None:
            return hit
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = lookup()  # otro hilo pudo calcularlo mientras esperábamos
            if hit is not None:
                return hit
            return compute()

    def clear(self) -> None:
        with self._guard:
            self._locks.clear()
