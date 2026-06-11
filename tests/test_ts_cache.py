"""Tests for the in-memory time-series cache and LTTB resampling in server/ts_cache.py."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from server.ts_cache import (
    TimeSeriesCache,
    _lttb_downsample,
    get_cache,
)

NS = 1_000_000_000  # 1 second in nanoseconds


def make_table(tstart, value, tend=None):
    cols = {
        "tstart": pa.array(tstart, type=pa.float64()),
        "value": pa.array(value, type=pa.float64()),
    }
    if tend is not None:
        cols["tend"] = pa.array(tend, type=pa.float64())
    return pa.table(cols)


class TestMakeKey:
    def test_key_format(self):
        key = TimeSeriesCache.make_key("cat", "sch", "c1", "ch1")
        assert key == "cat.sch.c1.ch1"


class TestLttbDownsample:
    def test_returns_input_when_smaller_than_target(self):
        t = np.array([0.0, 1.0, 2.0])
        v = np.array([10.0, 11.0, 12.0])
        t_out, v_out = _lttb_downsample(t, v, n_out=10)
        assert np.array_equal(t_out, t)
        assert np.array_equal(v_out, v)

    def test_downsamples_to_target_size(self):
        t = np.arange(1000, dtype=np.float64)
        v = np.sin(t / 50.0)
        t_out, _ = _lttb_downsample(t, v, n_out=100)
        assert len(t_out) == 100

    def test_preserves_endpoints(self):
        t = np.arange(1000, dtype=np.float64)
        v = np.sin(t / 50.0)
        t_out, _ = _lttb_downsample(t, v, n_out=50)
        assert t_out[0] == t[0]
        assert t_out[-1] == t[-1]


class TestLoadFromArrow:
    def test_loads_and_reports_metadata(self):
        cache = TimeSeriesCache()
        table = make_table([0 * NS, 1 * NS, 2 * NS], [1.0, 2.0, 3.0])
        ch = cache.load_from_arrow("k1", "ch1", table)
        assert ch.total_points == 3
        assert ch.t_min_ns == 0.0
        assert ch.t_max_ns == 2 * NS
        assert cache.is_loaded("k1")

    def test_sorts_unordered_timestamps(self):
        cache = TimeSeriesCache()
        table = make_table([2 * NS, 0 * NS, 1 * NS], [30.0, 10.0, 20.0])
        ch = cache.load_from_arrow("k1", "ch1", table)
        assert list(ch.expanded_t) == [0 * NS, 1 * NS, 2 * NS]
        assert list(ch.expanded_v) == [10.0, 20.0, 30.0]

    def test_idempotent_for_same_key(self):
        cache = TimeSeriesCache()
        table = make_table([0.0], [1.0])
        first = cache.load_from_arrow("k1", "ch1", table)
        second = cache.load_from_arrow("k1", "ch1", make_table([5.0], [9.0]))
        assert first is second  # cached object returned, not reloaded

    def test_memory_usage_tracked(self):
        cache = TimeSeriesCache()
        cache.load_from_arrow("k1", "ch1", make_table([0.0, 1.0], [1.0, 2.0]))
        # two float64 arrays of length 2 => 2 * (2 * 8) = 32 bytes
        assert cache.get_memory_usage() == 32


class TestResample:
    def test_raises_for_unloaded_key(self):
        cache = TimeSeriesCache()
        with pytest.raises(KeyError):
            cache.resample("missing", None, None)

    def test_full_range_returns_points(self):
        cache = TimeSeriesCache()
        cache.load_from_arrow("k1", 42, make_table([0 * NS, 1 * NS], [1.0, 2.0]))
        out = cache.resample("k1", None, None, n_points=5000)
        assert out["channel_id"] == 42
        assert out["total_points"] == 2
        assert out["window_points"] == 2
        # timestamps are converted to seconds in the output
        assert out["data"][0]["t"] == 0.0
        assert out["data"][1]["t"] == 1.0

    def test_window_filter(self):
        cache = TimeSeriesCache()
        t = [i * NS for i in range(10)]
        cache.load_from_arrow("k1", 1, make_table(t, list(range(10))))
        out = cache.resample("k1", x_min_ns=3 * NS, x_max_ns=5 * NS, n_points=5000)
        assert out["window_points"] == 3  # indices 3, 4, 5
        assert out["total_points"] == 10

    def test_empty_window_returns_no_data(self):
        cache = TimeSeriesCache()
        cache.load_from_arrow("k1", 1, make_table([0 * NS, 1 * NS], [1.0, 2.0]))
        out = cache.resample("k1", x_min_ns=100 * NS, x_max_ns=200 * NS)
        assert out["data"] == []
        assert out["window_points"] == 0

    def test_normalize_scales_to_unit_range(self):
        cache = TimeSeriesCache()
        cache.load_from_arrow("k1", 1, make_table([0 * NS, 1 * NS, 2 * NS], [10.0, 20.0, 30.0]))
        out = cache.resample("k1", None, None, normalize=True)
        v_norm = [p["v"] for p in out["data"]]
        assert min(v_norm) == 0.0
        assert max(v_norm) == 1.0
        # raw value preserved alongside normalized value
        assert out["data"][0]["v_raw"] == 10.0


class TestEviction:
    def test_lru_eviction_over_budget(self):
        # Each channel of length 4 uses 4 * 2 * 8 = 64 bytes; budget fits one.
        cache = TimeSeriesCache(max_memory_bytes=100)
        cache.load_from_arrow("a", 1, make_table([0.0, 1, 2, 3], [0.0, 1, 2, 3]))
        cache.load_from_arrow("b", 2, make_table([0.0, 1, 2, 3], [0.0, 1, 2, 3]))
        # Loading "b" pushed over budget; least-recently-used "a" should be evicted.
        assert cache.is_loaded("b")
        assert not cache.is_loaded("a")


class TestGetCache:
    def test_singleton(self):
        assert get_cache() is get_cache()
