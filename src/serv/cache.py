"""Bounded cache for rendered Markdown.

The key is ``(file path, sha256 of its bytes)``, exactly like the old
``functools.lru_cache``: a file edited on disk gets a new key and a fresh
render, while repeated requests for an unchanged file are free.

Size: an entry is the rendered HTML of one document, typically 20–200 KB and
occasionally larger for image-heavy pages. The default of 64 entries therefore
costs on the order of 10 MB, which is why the bound is configurable but small.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import threading
from typing import Callable, Generic, TypeVar

import deal

T = TypeVar("T")

DEFAULT_CAPACITY = 64


@dataclass(frozen=True)
class CacheStats:
    """Counters shown by the tray menu."""

    hits: int
    misses: int
    entries: int
    capacity: int


@deal.inv(
    lambda self: not getattr(self, "_initialized", False)
    or 0 <= len(self._entries) <= self._capacity,
    message="cache must stay within capacity",
)
class RenderCache(Generic[T]):
    """A small thread-safe LRU cache keyed by (path, content digest)."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._initialized = False
        self._capacity = capacity
        self._entries: OrderedDict[tuple[str, str], T] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._initialized = True

    @staticmethod
    def digest(source: bytes) -> str:
        """Return the content hash used as the second half of the key."""
        return sha256(source).hexdigest()

    def get(self, key: tuple[str, str]) -> T | None:
        """Return a cached value and mark it most recently used."""
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self._hits += 1
                return self._entries[key]
            return None

    def put(self, key: tuple[str, str], value: T) -> T:
        """Store a value, evicting the least recently used entry when full."""
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
        return value

    def render(self, key: tuple[str, str], factory: Callable[[], T]) -> T:
        """Return the cached value for key, or build and store it."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        with self._lock:
            self._misses += 1
        return self.put(key, value)

    def clear(self) -> None:
        """Drop every entry, e.g. after a config change."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> CacheStats:
        """Return a consistent snapshot of the counters."""
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                entries=len(self._entries),
                capacity=self._capacity,
            )


def file_digest(path: Path) -> str:
    """Hash one file so the cache key changes whenever its content does."""
    return RenderCache.digest(path.read_bytes())
