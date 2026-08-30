"""
================================================================================
CEREBRO-X |  CACHING LAYER
================================================================================
File: src/ml/cache.py

Multi-tier caching for:
  1. Molecule API lookups  (DrugBank, ChEMBL, PubChem — slow external calls)
  2. ML model predictions  (avoid re-inference for same input)
  3. DDS scoring results   (formulation rankings)
  4. API response caching  (GET endpoints with TTL)

Architecture:
  L1: In-process LRU cache (functools.lru_cache / dict)  → ~0ms
  L2: Redis cache (shared across workers/replicas)        → ~1ms
  L3: SQLite persistent cache (survives restarts)         → ~5ms
  L4: Original source (API call / ML inference)           → 100ms–10s

Cache invalidation:
  - TTL-based (molecule data: 24h, predictions: 1h, DDS scores: 6h)
  - Hash-based (Excel file hash → invalidate all downstream)
  - Manual flush via API endpoint (/cache/flush)

Thread-safe: all operations use threading.Lock or Redis atomic ops.
================================================================================
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

log = logging.getLogger("CEREBRO-CACHE")

# ─────────────────────────────────────────────────────────────────────────────
# Optional imports
# ─────────────────────────────────────────────────────────────────────────────
try:
    import redis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
REDIS_URL       = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_DB_PATH   = Path(os.environ.get("CACHE_DB_PATH", "outputs/cache.db"))
CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Default TTLs (seconds)
TTL_MOLECULE    = int(os.environ.get("CACHE_TTL_MOLECULE", 86400))   # 24h
TTL_PREDICTION  = int(os.environ.get("CACHE_TTL_PREDICTION", 3600))  # 1h
TTL_DDS_SCORE   = int(os.environ.get("CACHE_TTL_DDS", 21600))       # 6h
TTL_API_RESPONSE = int(os.environ.get("CACHE_TTL_API", 300))        # 5min


# ─────────────────────────────────────────────────────────────────────────────
# 1. In-Memory LRU Cache (L1)
# ─────────────────────────────────────────────────────────────────────────────
class LRUCache:
    """
    Thread-safe LRU cache with TTL support.
    Bounded by max_size to prevent memory leaks.
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        self._cache: dict[str, dict] = {}
        self._access_order: list = []
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if time.time() > entry["expires_at"]:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)
            return entry["value"]

    def set(self, key: str, value: Any, ttl: int = None):
        with self._lock:
            if len(self._cache) >= self._max_size:
                if self._access_order:
                    evict_key = self._access_order.pop(0)
                    self._cache.pop(evict_key, None)

            self._cache[key] = {
                "value":      value,
                "expires_at": time.time() + (ttl or self._default_ttl),
                "created_at": time.time(),
            }
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)

    def flush(self):
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size":      len(self._cache),
            "max_size":  self._max_size,
            "hits":      self._hits,
            "misses":    self._misses,
            "hit_rate":  round(self._hits / max(total, 1), 4),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Redis Cache (L2)
# ─────────────────────────────────────────────────────────────────────────────
class RedisCache:
    """
    Redis-backed cache shared across all API replicas and workers.
    Falls back to None (cache miss) if Redis unavailable.
    """

    PREFIX = "cerebro:"

    def __init__(self, redis_url: str = REDIS_URL):
        self._client = None
        if _HAS_REDIS:
            try:
                self._client = redis.from_url(
                    redis_url, socket_timeout=2,
                    decode_responses=True,
                )
                self._client.ping()
                log.info("[CACHE:REDIS] Connected")
            except Exception as e:
                log.warning(f"[CACHE:REDIS] Unavailable: {e}")
                self._client = None

    def _key(self, key: str, category: str = "general") -> str:
        # category is embedded in the key namespace so flush(pattern) can
        # actually find these entries — get/set/delete previously ignored
        # category entirely (key was just f"{PREFIX}{key}"), so
        # flush(f"{category}:*") never matched any real stored key and
        # was a silent no-op. Confirmed directly: a key built by the
        # @cached decorator for category="molecule" on fetch_molecule()
        # is stored as "cerebro:fetch_molecule:Donepezil", which doesn't
        # start with "cerebro:molecule:" — the pattern CacheManager.flush
        # searches for. That meant invalidate_on_excel_change() (whose
        # entire job is invalidating stale molecule/DDS data after a new
        # Excel upload) never actually cleared Redis in a multi-worker
        # deployment, only the in-process L1 cache and the SQLite L3
        # tier — stale cached data could keep being served from Redis
        # for up to its full TTL (up to 24h for molecule data) after the
        # researcher uploaded new input.
        return f"{self.PREFIX}{category}:{key}"

    def get(self, key: str, category: str = "general") -> Any | None:
        if not self._client:
            return None
        try:
            raw = self._client.get(self._key(key, category))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = 3600, category: str = "general"):
        if not self._client:
            return
        try:
            self._client.setex(
                self._key(key, category), ttl,
                json.dumps(value, default=str),
            )
        except Exception as e:
            log.warning(f"[CACHE:REDIS] Set failed: {e}")

    def delete(self, key: str, category: str = "general"):
        if self._client:
            try:
                self._client.delete(self._key(key, category))
            except Exception as _exc_bare:
                pass

    def flush(self, pattern: str = "*"):
        if not self._client:
            return
        try:
            keys = self._client.keys(f"{self.PREFIX}{pattern}")
            if keys:
                self._client.delete(*keys)
            log.info(f"[CACHE:REDIS] Flushed {len(keys)} keys")
        except Exception as e:
            log.warning(f"[CACHE:REDIS] Flush failed: {e}")

    @property
    def available(self) -> bool:
        return self._client is not None


# ─────────────────────────────────────────────────────────────────────────────
# 3. SQLite Persistent Cache (L3)
# ─────────────────────────────────────────────────────────────────────────────
class SQLiteCache:
    """Persistent cache that survives process restarts."""

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                category    TEXT DEFAULT '',
                expires_at  REAL NOT NULL,
                created_at  REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_exp ON cache(expires_at)")
        conn.commit()
        conn.close()

    def get(self, key: str) -> Any | None:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT value FROM cache WHERE key = ? AND expires_at > ?",
            (key, time.time())
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def set(self, key: str, value: Any, ttl: int = 3600, category: str = ""):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO cache (key, value, category, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (key, json.dumps(value, default=str), category,
              time.time() + ttl, time.time()))
        conn.commit()
        conn.close()

    def delete(self, key: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        conn.close()

    def flush(self, category: str = None):
        conn = sqlite3.connect(self.db_path)
        if category:
            conn.execute("DELETE FROM cache WHERE category = ?", (category,))
        else:
            conn.execute("DELETE FROM cache")
        conn.commit()
        conn.close()

    def cleanup_expired(self) -> int:
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
        deleted = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        conn.close()
        return deleted


# ─────────────────────────────────────────────────────────────────────────────
# 4. Unified Cache Manager (L1 → L2 → L3 → source)
# ─────────────────────────────────────────────────────────────────────────────
class CacheManager:
    """
    Multi-tier cache with read-through and write-through.

    Lookup order: L1 (memory) → L2 (Redis) → L3 (SQLite) → source
    Write order:  source → L3 → L2 → L1
    """

    def __init__(self):
        self.l1 = LRUCache(max_size=2000)
        self.l2 = RedisCache()
        self.l3 = SQLiteCache()

    def get(self, key: str, category: str = "general") -> Any | None:
        # L1
        val = self.l1.get(key)
        if val is not None:
            return val

        # L2
        val = self.l2.get(key, category)
        if val is not None:
            self.l1.set(key, val)  # backfill L1
            return val

        # L3
        val = self.l3.get(key)
        if val is not None:
            self.l1.set(key, val)
            self.l2.set(key, val, category=category)
            return val

        return None

    def set(self, key: str, value: Any, ttl: int = 3600,
            category: str = "general"):
        self.l3.set(key, value, ttl, category)
        self.l2.set(key, value, ttl, category)
        self.l1.set(key, value, ttl)

    def delete(self, key: str, category: str = "general"):
        self.l1.delete(key)
        self.l2.delete(key, category)
        self.l3.delete(key)

    def flush(self, category: str = None):
        self.l1.flush()
        if category:
            self.l2.flush(f"{category}:*")
            self.l3.flush(category)
        else:
            self.l2.flush()
            self.l3.flush()
        log.info(f"[CACHE] Flushed all tiers (category={category})")

    @property
    def stats(self) -> dict:
        return {
            "l1_memory": self.l1.stats,
            "l2_redis":  {"available": self.l2.available},
            "l3_sqlite": {"path": str(self.l3.db_path)},
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cache Decorators
# ─────────────────────────────────────────────────────────────────────────────
_global_cache = None

def get_cache() -> CacheManager:
    global _global_cache
    if _global_cache is None:
        _global_cache = CacheManager()
    return _global_cache


def cached(ttl: int = 3600, category: str = "general",
           key_prefix: str = ""):
    """
    Decorator: caches function results across all tiers.

    Usage:
        @cached(ttl=86400, category="molecule")
        def fetch_molecule(drug_name: str) -> dict:
            return expensive_api_call(drug_name)
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()
            cache_key = _build_key(key_prefix or func.__name__, args, kwargs)

            result = cache.get(cache_key, category)
            if result is not None:
                log.debug(f"[CACHE HIT] {cache_key}")
                return result

            result = func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, result, ttl, category)
            return result
        return wrapper
    return decorator


def _build_key(prefix: str, args: tuple, kwargs: dict) -> str:
    parts = [prefix]
    import json as _json

    def _safe_ser(obj) -> str:
        """Serialize ANY Python type to stable string — fixes unhashable dict bug."""
        if obj is None: return "None"
        if isinstance(obj, (str, int, float, bool)): return str(obj)[:120]
        if isinstance(obj, (dict,)):
            try: return _json.dumps(obj, sort_keys=True, default=str)[:200]
            except: return str(sorted(str(k) for k in obj))[:200]
        if isinstance(obj, (list, tuple, set)):
            try: return _json.dumps(list(obj), default=str)[:200]
            except: return str(obj)[:200]
        return str(obj)[:120]

    for a in args:
        parts.append(_safe_ser(a))
    for k, v in sorted(kwargs.items()):
        parts.append(f"{k}={_safe_ser(v)}")
    raw = ":".join(parts)
    if len(raw) > 200:
        return f"{prefix}:{hashlib.md5(raw.encode()).hexdigest()}"
    return raw


def invalidate_on_excel_change(excel_path: str):
    """
    Invalidates all cached data when the input Excel file changes.

    NOT currently wired into run.py or the real pipeline -- confirmed via
    repo-wide grep, nothing calls get_cache()/CacheManager()/@cached
    anywhere outside this file and its own tests. This whole L1/L2/L3
    caching layer is dormant infrastructure. The real, live per-trial
    cache invalidation is trial_manager.invalidate_molecule_cache(),
    which run.py's watcher actually calls (JSON files under
    outputs/molecule_cache/ + the cerebro_knowledge.db SQLite table).
    This docstring previously claimed "Called by the file watcher in
    run.py", which was never true.
    """
    cache = get_cache()
    cache.flush("molecule")
    cache.flush("dds")
    cache.flush("prediction")
    log.info(f"[CACHE] Invalidated all caches — Excel changed: {excel_path}")