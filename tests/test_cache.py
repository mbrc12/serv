"""The digest-keyed render cache."""

from __future__ import annotations

from serv.cache import RenderCache


def test_cache_hit_returns_same_value() -> None:
    cache: RenderCache[str] = RenderCache(4)
    assert cache.get(("a.md", "1")) is None
    cache.put(("a.md", "1"), "first")
    assert cache.get(("a.md", "1")) == "first"
    assert cache.stats().hits == 1


def test_cache_evicts_least_recently_used() -> None:
    cache: RenderCache[str] = RenderCache(2)
    cache.put(("a", "1"), "a")
    cache.put(("b", "1"), "b")
    assert cache.get(("a", "1")) == "a"  # a is now the most recent
    cache.put(("c", "1"), "c")  # b is evicted
    assert cache.get(("b", "1")) is None
    assert cache.get(("a", "1")) == "a"
    assert cache.get(("c", "1")) == "c"


def test_cache_digest_changes_with_content() -> None:
    assert RenderCache.digest(b"one") != RenderCache.digest(b"two")
    assert RenderCache.digest(b"one") == RenderCache.digest(b"one")


def test_render_counts_one_miss_per_render() -> None:
    cache: RenderCache[str] = RenderCache(4)
    calls = 0

    def factory() -> str:
        nonlocal calls
        calls += 1
        return "page"

    assert cache.render(("a", "1"), factory) == "page"
    assert cache.render(("a", "1"), factory) == "page"
    assert calls == 1
    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.entries) == (1, 1, 1)
