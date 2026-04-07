"""In-memory Polars cache + LTTB resample engine for time series data.

Stores expanded RLE time series as numpy arrays. Supports instant (<50ms)
LTTB downsampling on any zoom window via tsdownsample.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ChannelData:
    """One loaded channel's data, ready for resampling."""

    cache_key: str
    channel_id: int
    expanded_t: np.ndarray  # timestamps in nanoseconds (float64)
    expanded_v: np.ndarray  # values (float64)
    total_points: int
    t_min_ns: float
    t_max_ns: float
    last_accessed: float = field(default_factory=time.monotonic)
    memory_bytes: int = 0


# ---------------------------------------------------------------------------
# RLE expansion (vectorized in Polars)
# ---------------------------------------------------------------------------


def expand_rle(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Expand RLE intervals to step-pair arrays.

    Each RLE row (tstart, tend, value) becomes two points:
      (tstart, value) and (tend, value)  [if tend != tstart]

    Returns (timestamps_ns, values) as float64 numpy arrays.
    """
    starts = df.select(pl.col("tstart").alias("t"), pl.col("value"))
    ends = df.filter(pl.col("tend") != pl.col("tstart")).select(
        pl.col("tend").alias("t"), pl.col("value")
    )
    expanded = pl.concat([starts, ends]).sort("t")

    t_arr = expanded["t"].to_numpy(zero_copy_only=False).astype(np.float64)
    v_arr = expanded["value"].to_numpy(zero_copy_only=False).astype(np.float64)
    return t_arr, v_arr


# ---------------------------------------------------------------------------
# LTTB downsampling
# ---------------------------------------------------------------------------


def _lttb_downsample(
    t: np.ndarray, v: np.ndarray, n_out: int
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample using LTTB via tsdownsample (Rust), with numpy fallback."""
    if len(t) <= n_out:
        return t, v

    try:
        from tsdownsample import LTTBDownsampler

        indices = LTTBDownsampler().downsample(t, v, n_out=n_out)
        return t[indices], v[indices]
    except ImportError:
        indices = np.round(np.linspace(0, len(t) - 1, n_out)).astype(int)
        return t[indices], v[indices]


# ---------------------------------------------------------------------------
# Cache singleton
# ---------------------------------------------------------------------------


class TimeSeriesCache:
    """In-memory cache of expanded time series channels with LTTB resampling."""

    def __init__(self, max_memory_bytes: int = 8 * 1024**3):
        self._cache: dict[str, ChannelData] = {}
        self._max_memory_bytes = max_memory_bytes

    @staticmethod
    def make_key(catalog: str, schema: str, container_id: int, channel_id: int) -> str:
        return f"{catalog}.{schema}.{container_id}.{channel_id}"

    def is_loaded(self, cache_key: str) -> bool:
        return cache_key in self._cache

    def get_memory_usage(self) -> int:
        return sum(ch.memory_bytes for ch in self._cache.values())

    def load_from_polars(
        self,
        cache_key: str,
        channel_id: int,
        df: pl.DataFrame,
    ) -> ChannelData:
        """Load a channel from a Polars DataFrame of RLE rows into the cache.

        Args:
            cache_key: Unique identifier for this channel.
            channel_id: The channel ID.
            df: DataFrame with columns [tstart, tend, value].

        Returns:
            The cached ChannelData.
        """
        if cache_key in self._cache:
            ch = self._cache[cache_key]
            ch.last_accessed = time.monotonic()
            return ch

        t0 = time.monotonic()
        t_arr, v_arr = expand_rle(df)
        expand_ms = (time.monotonic() - t0) * 1000

        mem = t_arr.nbytes + v_arr.nbytes
        logger.info(
            "Expanded %s: %d RLE rows → %d points (%.1f MB) in %.0f ms",
            cache_key,
            len(df),
            len(t_arr),
            mem / 1024**2,
            expand_ms,
        )

        ch = ChannelData(
            cache_key=cache_key,
            channel_id=channel_id,
            expanded_t=t_arr,
            expanded_v=v_arr,
            total_points=len(t_arr),
            t_min_ns=float(t_arr[0]) if len(t_arr) > 0 else 0.0,
            t_max_ns=float(t_arr[-1]) if len(t_arr) > 0 else 0.0,
            memory_bytes=mem,
        )
        self._cache[cache_key] = ch

        # Evict LRU if over memory budget
        while self.get_memory_usage() > self._max_memory_bytes and len(self._cache) > 1:
            self._evict_lru(exclude=cache_key)

        return ch

    def resample(
        self,
        cache_key: str,
        x_min_ns: float | None,
        x_max_ns: float | None,
        n_points: int = 5000,
        normalize: bool = False,
    ) -> dict:
        """Resample a cached channel to n_points using LTTB.

        Args:
            cache_key: Cache key from load.
            x_min_ns: Start of visible window (nanoseconds), or None for full range.
            x_max_ns: End of visible window (nanoseconds), or None for full range.
            n_points: Target number of output points.
            normalize: If True, min-max normalize values to [0, 1].

        Returns:
            Dict with keys: channel_id, data, total_points, window_points.
        """
        ch = self._cache.get(cache_key)
        if ch is None:
            raise KeyError(f"Channel {cache_key} not loaded")

        ch.last_accessed = time.monotonic()
        t_arr = ch.expanded_t
        v_arr = ch.expanded_v

        # Window filter via binary search
        if x_min_ns is not None or x_max_ns is not None:
            lo = 0
            hi = len(t_arr)
            if x_min_ns is not None:
                lo = int(np.searchsorted(t_arr, x_min_ns, side="left"))
            if x_max_ns is not None:
                hi = int(np.searchsorted(t_arr, x_max_ns, side="right"))
            t_arr = t_arr[lo:hi]
            v_arr = v_arr[lo:hi]

        window_points = len(t_arr)

        if window_points == 0:
            return {
                "channel_id": ch.channel_id,
                "data": [],
                "total_points": ch.total_points,
                "window_points": 0,
            }

        # LTTB downsample
        t_ds, v_ds = _lttb_downsample(t_arr, v_arr, n_points)

        # Build output
        if normalize:
            v_min = float(ch.expanded_v.min())
            v_max = float(ch.expanded_v.max())
            v_range = v_max - v_min if v_max != v_min else 1.0
            v_norm = (v_ds - v_min) / v_range
            data = [
                {"t": float(t) / 1e9, "v": round(float(vn), 6), "v_raw": round(float(vr), 6)}
                for t, vn, vr in zip(t_ds, v_norm, v_ds)
            ]
        else:
            data = [
                {"t": float(t) / 1e9, "v": round(float(v), 6)}
                for t, v in zip(t_ds, v_ds)
            ]

        return {
            "channel_id": ch.channel_id,
            "data": data,
            "total_points": ch.total_points,
            "window_points": window_points,
        }

    def _evict_lru(self, exclude: str | None = None) -> None:
        """Remove the least-recently-accessed entry (except `exclude`)."""
        oldest_key = None
        oldest_time = float("inf")
        for key, ch in self._cache.items():
            if key == exclude:
                continue
            if ch.last_accessed < oldest_time:
                oldest_time = ch.last_accessed
                oldest_key = key

        if oldest_key:
            evicted = self._cache.pop(oldest_key)
            logger.info(
                "Evicted %s (%.1f MB) from cache",
                oldest_key,
                evicted.memory_bytes / 1024**2,
            )


# Module-level singleton
_cache_instance: TimeSeriesCache | None = None


def get_cache() -> TimeSeriesCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = TimeSeriesCache()
    return _cache_instance
