"""
tests/unit/test_cache.py
------------------------
Unit tests for the cache service key building logic.

We don't test actual Redis operations here (that's integration testing).
We test the pure logic — key construction and TTL constants.

The key building logic matters because:
  - Inconsistent keys = cache misses even when data is cached
  - Keys that change on every call = cache never hits
  - Keys without proper namespacing = cache collisions between domains
"""

import pytest
from app.services.cache import CacheService, CacheTTL


class TestCacheKeyBuilding:

    def setup_method(self):
        self.cache = CacheService()

    def test_build_key_joins_parts_with_colon(self):
        key = self.cache.build_key("courses", "single", "crs_5010")
        assert key == "courses:single:crs_5010"

    def test_build_key_skips_none_values(self):
        """None values should be excluded — they represent absent filters."""
        key = self.cache.build_key("courses", None, "crs_5010")
        assert key == "courses:crs_5010"
        assert "None" not in key

    def test_build_list_key_is_deterministic(self):
        """
        Same filters in any order should produce the same cache key.
        This is critical — if filter order matters, cache misses happen
        when the same query is made with parameters in different order.
        """
        key1 = self.cache.build_list_key(
            "courses", semester="fall_2026", program_id="prog_cs_101"
        )
        key2 = self.cache.build_list_key(
            "courses", program_id="prog_cs_101", semester="fall_2026"
        )
        assert key1 == key2

    def test_build_list_key_different_filters_produce_different_keys(self):
        """Different filters must produce different keys — no collisions."""
        key1 = self.cache.build_list_key("courses", semester="fall_2026")
        key2 = self.cache.build_list_key("courses", semester="spring_2026")
        assert key1 != key2

    def test_build_list_key_different_domains_produce_different_keys(self):
        """Courses and books with same filter should not collide."""
        key1 = self.cache.build_list_key("courses", genre="computer_science")
        key2 = self.cache.build_list_key("books", genre="computer_science")
        assert key1 != key2

    def test_build_list_key_starts_with_domain(self):
        """Keys should be prefixed with domain for pattern-based invalidation."""
        key = self.cache.build_list_key("courses", semester="fall_2026")
        assert key.startswith("courses:")

    def test_build_list_key_contains_list_segment(self):
        key = self.cache.build_list_key("books", genre="engineering")
        assert ":list:" in key

    def test_none_filters_excluded_from_key(self):
        """
        None filters should not affect the cache key.
        A query with semester=None should produce the same key as
        a query that just doesn't include semester at all.
        """
        key1 = self.cache.build_list_key("courses", semester=None, program_id="prog_cs_101")
        key2 = self.cache.build_list_key("courses", program_id="prog_cs_101")
        assert key1 == key2


class TestCacheTTL:
    """Verify TTL constants make sense — programs cache longer than books."""

    def test_programs_cache_longer_than_courses(self):
        assert CacheTTL.PROGRAMS > CacheTTL.COURSE_LIST

    def test_course_list_cache_longer_than_single_book(self):
        """Course list is less volatile than individual book availability."""
        assert CacheTTL.COURSE_LIST >= CacheTTL.BOOK_SINGLE

    def test_all_ttls_are_positive(self):
        ttls = [
            CacheTTL.PROGRAMS, CacheTTL.COURSE_LIST, CacheTTL.COURSE_SINGLE,
            CacheTTL.BOOK_LIST, CacheTTL.BOOK_SINGLE,
            CacheTTL.FACULTY_LIST, CacheTTL.FACULTY_SINGLE,
        ]
        for ttl in ttls:
            assert ttl > 0
