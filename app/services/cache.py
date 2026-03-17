"""
app/services/cache.py
---------------------
Redis caching service.

This is a reusable layer that sits between your routers and Redis.
Routers don't talk to Redis directly — they go through this service.
Why? Because if you ever swap Redis for Memcached or a different cache,
you change one file, not every router.

The pattern we implement: Cache-Aside (Lazy Loading)
1. Request comes in — check the cache first
2. Cache hit → return cached data immediately (fast path)
3. Cache miss → query the database, store result in cache, return result

This is the most common caching pattern for read-heavy APIs.

Key naming convention — critical for cache invalidation:
  courses:list:fall_2026:prog_cs_101    ← course list filtered by semester + program
  courses:single:crs_5010               ← individual course
  books:list:computer_science           ← book list filtered by genre
  books:single:book_301                 ← individual book
  programs:list                         ← all programs (rarely changes)

The prefix structure (domain:type:filters) means you can invalidate
all course caches with a single pattern delete when a course changes.
"""

import json
import hashlib
from typing import Any, Optional
import redis.asyncio as aioredis
from app.core.config import get_settings

settings = get_settings()

# ── Redis Connection Pool ─────────────────────────────────────────────────────
# Same pooling concept as PostgreSQL — reuse connections instead of
# creating new ones per request. Redis connections are cheap but not free.
_redis_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    Get the Redis connection from the pool.
    Initialize the pool on first call (lazy initialization).
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


async def close_redis():
    """Call this on app shutdown to cleanly close all connections."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


# ── Cache Service ─────────────────────────────────────────────────────────────

class CacheService:
    """
    Reusable caching operations.
    
    Used like this in a router:
    
        cache = CacheService()
        
        # Try cache first
        cached = await cache.get("courses:list:fall_2026")
        if cached:
            return cached
        
        # Cache miss — query DB
        result = await db.execute(...)
        
        # Store in cache for 5 minutes
        await cache.set("courses:list:fall_2026", result, ttl=300)
        return result
    """

    async def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.
        Returns None on cache miss OR if Redis is unavailable.
        
        The try/except is intentional — if Redis goes down, your API
        should still work (just slower, hitting the DB every time).
        Never let a cache failure take down your API.
        """
        try:
            redis = await get_redis()
            value = await redis.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception:
            # Redis unavailable — fail gracefully, let request hit DB
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """
        Store a value in cache with a TTL (seconds).
        Returns True on success, False on failure.
        Serializes to JSON — only works with JSON-serializable data.
        """
        try:
            redis = await get_redis()
            serialized = json.dumps(value, default=str)
            await redis.setex(key, ttl, serialized)
            return True
        except Exception:
            return False

    async def delete(self, key: str) -> bool:
        """Delete a specific cache key. Call this when underlying data changes."""
        try:
            redis = await get_redis()
            await redis.delete(key)
            return True
        except Exception:
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.
        Use for cache invalidation when a category of data changes.
        
        Example: delete_pattern("courses:*") clears all course caches
        when any course is updated.
        
        Returns count of deleted keys.
        
        Note: SCAN is used instead of KEYS for safety.
        KEYS blocks Redis until it scans the entire keyspace.
        SCAN iterates incrementally — safe for production use.
        """
        try:
            redis = await get_redis()
            deleted = 0
            async for key in redis.scan_iter(match=pattern):
                await redis.delete(key)
                deleted += 1
            return deleted
        except Exception:
            return 0

    def build_key(self, *parts: str) -> str:
        """
        Build a consistent cache key from parts.
        
        build_key("courses", "list", "fall_2026", "prog_cs_101")
        → "courses:list:fall_2026:prog_cs_101"
        
        For complex filter combinations (many query params), we hash the
        filter string so the key stays a reasonable length.
        """
        return ":".join(str(p) for p in parts if p is not None)

    def build_list_key(self, domain: str, **filters) -> str:
        """
        Build a cache key for a list endpoint with arbitrary filters.
        
        build_list_key("courses", semester="fall_2026", program_id="prog_cs_101", page=1)
        → "courses:list:a3f9b2..." (hash of the filter combination)
        
        Hashing ensures consistent key length regardless of how many filters.
        """
        # Sort filters for consistent key regardless of parameter order
        filter_str = "&".join(f"{k}={v}" for k, v in sorted(filters.items()) if v is not None)
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:12]
        return f"{domain}:list:{filter_hash}"


# ── TTL Constants ─────────────────────────────────────────────────────────────
# Define TTLs in one place — makes them easy to tune
class CacheTTL:
    PROGRAMS = 3600          # 1 hour  — programs almost never change
    COURSE_LIST = 300        # 5 min   — high traffic, low change frequency
    COURSE_SINGLE = 120      # 2 min   — individual course
    BOOK_LIST = 120          # 2 min   — availability changes with borrowings
    BOOK_SINGLE = 60         # 1 min   — fresher for availability accuracy
    FACULTY_LIST = 600       # 10 min  — faculty changes rarely
    FACULTY_SINGLE = 300     # 5 min


# Global instance — import this in routers
cache = CacheService()
