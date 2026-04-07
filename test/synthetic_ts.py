"""Synthetic time series data generator for local testing.

Generates realistic RLE data for multiple signal types and loads them
directly into the TimeSeriesCache, bypassing the SQL connector.

Usage:
    from test.synthetic_ts import load_synthetic_data
    load_synthetic_data()  # populates cache with container_id=0
"""

from __future__ import annotations

import numpy as np
import pyarrow as pa

# Synthetic container_id — the routes detect this as the synthetic marker
SYNTHETIC_CONTAINER_ID = 0

# Signal definitions: (channel_id, name, unit, generator, value_range)
SYNTHETIC_SIGNALS = [
    {
        "channel_id": 1,
        "channel_name": "EngineSpeed",
        "unit": "rpm",
        "min_value": 800.0,
        "max_value": 6500.0,
        "sample_count": 0,  # filled at generation time
    },
    {
        "channel_id": 2,
        "channel_name": "OilTemperature",
        "unit": "°C",
        "min_value": 60.0,
        "max_value": 130.0,
        "sample_count": 0,
    },
    {
        "channel_id": 3,
        "channel_name": "BatteryVoltage",
        "unit": "V",
        "min_value": 11.5,
        "max_value": 14.8,
        "sample_count": 0,
    },
    {
        "channel_id": 4,
        "channel_name": "BoostPressure",
        "unit": "bar",
        "min_value": 0.0,
        "max_value": 2.5,
        "sample_count": 0,
    },
    {
        "channel_id": 5,
        "channel_name": "VehicleSpeed",
        "unit": "km/h",
        "min_value": 0.0,
        "max_value": 250.0,
        "sample_count": 0,
    },
    {
        "channel_id": 6,
        "channel_name": "ThrottlePosition",
        "unit": "%",
        "min_value": 0.0,
        "max_value": 100.0,
        "sample_count": 0,
    },
]

# Synthetic container metadata
SYNTHETIC_CONTAINER = {
    "container_id": SYNTHETIC_CONTAINER_ID,
    "filename": "synthetic_test_drive.mf4",
    "vehicle_key": "TEST-VEHICLE-001",
    "start_dt": "2024-03-15T10:00:00",
    "stop_dt": "2024-03-15T10:30:00",
    "num_channels": len(SYNTHETIC_SIGNALS),
    "duration_ms": 1800_000,
}


def _generate_signal(
    channel_id: int,
    n_points: int,
    duration_ns: int,
    rng: np.random.Generator,
) -> pl.DataFrame:
    """Generate RLE data for one synthetic signal.

    Returns DataFrame with columns [tstart, tend, value].
    """
    sig = next(s for s in SYNTHETIC_SIGNALS if s["channel_id"] == channel_id)
    v_min, v_max = sig["min_value"], sig["max_value"]
    v_range = v_max - v_min
    v_mid = (v_min + v_max) / 2

    t = np.linspace(0, duration_ns, n_points + 1, dtype=np.int64)
    tstart = t[:-1]
    tend = t[1:]

    # Each signal gets a distinct waveform for visual variety
    phase = np.linspace(0, 1, n_points)

    if channel_id == 1:  # EngineSpeed: sine + noise (simulates RPM)
        base = np.sin(2 * np.pi * 3 * phase) * 0.4 + 0.5
        noise = rng.normal(0, 0.05, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    elif channel_id == 2:  # OilTemperature: slow ramp + small noise
        base = 0.2 + 0.6 * phase + 0.05 * np.sin(2 * np.pi * 8 * phase)
        noise = rng.normal(0, 0.02, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    elif channel_id == 3:  # BatteryVoltage: mostly stable with dips
        base = np.full(n_points, 0.7)
        # Add periodic dips
        for center in np.linspace(0.1, 0.9, 5):
            dip = np.exp(-((phase - center) ** 2) / 0.001) * 0.4
            base -= dip
        noise = rng.normal(0, 0.01, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    elif channel_id == 4:  # BoostPressure: correlated with EngineSpeed
        base = np.sin(2 * np.pi * 3 * phase) * 0.35 + 0.5
        # Lag slightly behind engine speed
        base = np.roll(base, n_points // 50)
        noise = rng.normal(0, 0.03, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    elif channel_id == 5:  # VehicleSpeed: ramp-up, cruise, ramp-down
        base = np.piecewise(
            phase,
            [phase < 0.2, (phase >= 0.2) & (phase < 0.7), phase >= 0.7],
            [lambda x: x / 0.2 * 0.8, lambda x: 0.8 + 0.05 * np.sin(10 * np.pi * x), lambda x: 0.8 * (1 - (x - 0.7) / 0.3)],
        )
        noise = rng.normal(0, 0.02, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    else:  # ThrottlePosition: step function with noise
        base = np.zeros(n_points)
        steps = rng.choice([0.1, 0.3, 0.5, 0.7, 0.9], size=20)
        step_positions = np.sort(rng.integers(0, n_points, size=20))
        for pos, val in zip(step_positions, steps):
            base[pos:] = val
        noise = rng.normal(0, 0.02, n_points)
        values = v_min + (base + noise).clip(0, 1) * v_range

    return pa.table({
        "tstart": pa.array(tstart),
        "tend": pa.array(tend),
        "value": pa.array(values.astype(np.float64)),
    })


def load_synthetic_data(
    n_points_per_signal: int = 1_000_000,
) -> dict[int, dict]:
    """Generate synthetic data and load into the global TimeSeriesCache.

    Args:
        n_points_per_signal: Number of RLE rows per signal. Default 1M for
            responsive local testing.

    Returns:
        Dict mapping channel_id → {"cache_key": ..., "total_points": ..., ...}
    """
    from server.ts_cache import TimeSeriesCache, get_cache

    cache = get_cache()
    rng = np.random.default_rng(42)
    duration_ns = SYNTHETIC_CONTAINER["duration_ms"] * 1_000_000  # 30 min in ns
    results = {}

    for sig in SYNTHETIC_SIGNALS:
        channel_id = sig["channel_id"]
        cache_key = TimeSeriesCache.make_key(
            "synthetic", "test", SYNTHETIC_CONTAINER_ID, channel_id
        )

        if cache.is_loaded(cache_key):
            results[channel_id] = {"cache_key": cache_key, "already_loaded": True}
            continue

        table = _generate_signal(channel_id, n_points_per_signal, duration_ns, rng)
        ch = cache.load_from_arrow(cache_key, channel_id, table)

        sig["sample_count"] = ch.total_points
        results[channel_id] = {
            "cache_key": cache_key,
            "total_points": ch.total_points,
            "t_min_ns": ch.t_min_ns,
            "t_max_ns": ch.t_max_ns,
        }

    return results
