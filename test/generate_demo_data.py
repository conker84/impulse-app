"""
One-time script to generate synthetic demo data for the Mountain Pass Overheating scenario.

Writes to: maximhammer_catalog.impulse_moon
  - channels          (RLE time series)
  - channel_metrics   (per-channel stats)
  - channel_tags      (channel_name, unit)
  - container_metrics (session summary)
  - container_tags    (vehicle metadata)

Scenario: 45-minute VW Golf GTI prototype cooling system validation on an Alpine
test loop near Garmisch-Partenkirchen. The team is validating a redesigned cooling
system for the next-gen GTI. During the mountain climb section, the cooling system
fails to keep up with sustained high-load, low-airflow conditions — coolant
temperature exceeds 105°C twice.

Drive phases:
  0–5 min   Town warmup    — cold start from Garmisch, coolant 40→85°C, low RPM/speed
  5–20 min  Highway cruise — B2 toward Mittenwald, 120 km/h, 2500 RPM, coolant stable 88°C
  20–30 min Mountain climb — Karwendel pass, speed drops to 50-70 km/h, RPM 4000-5500,
                             throttle >80%, engine load >85%, coolant climbs to 108-112°C,
                             oil temp follows with ~60s lag
  30–38 min Descent        — downhill engine braking, low throttle, coolant recovers
  38–45 min Highway return — back to Garmisch, normal cruise, stable temps

Signal generation logic:
  - Engine Speed:    base profile per phase + sinusoidal variation + noise
  - Vehicle Speed:   smooth transitions between phase targets
  - Coolant Temp:    thermal model driven by engine load with cooling lag
  - Oil Temp:        follows coolant with ~60s thermal lag (larger thermal mass)
  - Throttle Pos:    correlated with RPM demand per phase
  - Intake Pressure: correlated with RPM and throttle (manifold load proxy)
  - Engine Load:     computed from RPM × throttle, the "smoking gun" for root cause

Usage:
  DATABRICKS_CONFIG_PROFILE=fe-vm-maximhammer python3 test/generate_demo_data.py
"""

from __future__ import annotations

import numpy as np
from databricks.sdk import WorkspaceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CATALOG = "maximhammer_catalog"
SCHEMA = "impulse_moon"
CONTAINER_ID = 1
VEHICLE_KEY = "VW_Golf"
SAMPLE_RATE_HZ = 100  # 100 Hz → 100 samples/sec
DURATION_S = 45 * 60  # 45 minutes
N_POINTS = DURATION_S * SAMPLE_RATE_HZ  # 270,000 raw points

# Timestamps in nanoseconds (relative, starting at 0)
START_EPOCH_MS = 1753185600000  # 2025-07-22 08:00:00 UTC in ms
START_NS = 0
END_NS = DURATION_S * 1_000_000_000  # 45 min in ns

SIGNALS = [
    {"channel_id": 1, "channel_name": "Engine Speed",          "unit": "RPM"},
    {"channel_id": 2, "channel_name": "Vehicle Speed",         "unit": "km/h"},
    {"channel_id": 3, "channel_name": "Coolant Temperature",   "unit": "°C"},
    {"channel_id": 4, "channel_name": "Oil Temperature",       "unit": "°C"},
    {"channel_id": 5, "channel_name": "Throttle Position",     "unit": "%"},
    {"channel_id": 6, "channel_name": "Intake Pressure",       "unit": "kPa"},
    {"channel_id": 7, "channel_name": "Engine Load",            "unit": "%"},
]

# ---------------------------------------------------------------------------
# Phase boundaries (in seconds)
# ---------------------------------------------------------------------------
CITY_END = 5 * 60       # 300s
HWY1_END = 20 * 60      # 1200s
CLIMB_END = 30 * 60     # 1800s
DESC_END = 38 * 60      # 2280s
# HWY2 ends at DURATION_S = 2700s


def _smooth(x: np.ndarray, window: int = 51) -> np.ndarray:
    """Moving average smoothing with edge padding to avoid boundary artifacts."""
    pad = window // 2
    padded = np.pad(x, pad, mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")


def _phase_mask(t_s: np.ndarray, start: float, end: float) -> np.ndarray:
    return (t_s >= start) & (t_s < end)


def generate_signals(rng: np.random.Generator) -> dict[int, np.ndarray]:
    """Generate all 7 signal arrays. Returns {channel_id: values}."""
    t_s = np.linspace(0, DURATION_S, N_POINTS)  # time in seconds

    # ---- Engine Speed (RPM) ----
    rpm = np.zeros(N_POINTS)
    # City: idle + low speed driving, 800-1800 RPM
    m = _phase_mask(t_s, 0, CITY_END)
    rpm[m] = 800 + 700 * np.sin(2 * np.pi * 0.02 * t_s[m]) + 300 * rng.random(m.sum())

    # Highway: cruise at 2300-2700 RPM
    m = _phase_mask(t_s, CITY_END, HWY1_END)
    rpm[m] = 2500 + 200 * np.sin(2 * np.pi * 0.01 * t_s[m]) + 100 * rng.random(m.sum())

    # Mountain climb: 3800-5500 RPM with aggressive variation
    m = _phase_mask(t_s, HWY1_END, CLIMB_END)
    climb_progress = (t_s[m] - HWY1_END) / (CLIMB_END - HWY1_END)
    rpm[m] = 4200 + 800 * np.sin(2 * np.pi * 0.05 * t_s[m]) + 500 * climb_progress + 200 * rng.random(m.sum())

    # Descent: engine braking 1500-2500 RPM
    m = _phase_mask(t_s, CLIMB_END, DESC_END)
    rpm[m] = 2000 + 500 * np.sin(2 * np.pi * 0.015 * t_s[m]) + 150 * rng.random(m.sum())

    # Highway return: 2300-2700 RPM
    m = _phase_mask(t_s, DESC_END, DURATION_S + 1)
    rpm[m] = 2500 + 200 * np.sin(2 * np.pi * 0.01 * t_s[m]) + 100 * rng.random(m.sum())

    rpm = _smooth(np.clip(rpm, 600, 6000), window=101)

    # ---- Vehicle Speed (km/h) ----
    speed = np.zeros(N_POINTS)
    # City: 0-50 km/h, stop-and-go
    m = _phase_mask(t_s, 0, CITY_END)
    speed[m] = 25 + 20 * np.sin(2 * np.pi * 0.008 * t_s[m]) + 5 * rng.random(m.sum())

    # Highway: 110-130 km/h
    m = _phase_mask(t_s, CITY_END, HWY1_END)
    speed[m] = 120 + 8 * np.sin(2 * np.pi * 0.005 * t_s[m]) + 3 * rng.random(m.sum())

    # Mountain climb: drops to 50-75 km/h (slow climb despite high RPM)
    m = _phase_mask(t_s, HWY1_END, CLIMB_END)
    speed[m] = 60 + 10 * np.sin(2 * np.pi * 0.01 * t_s[m]) + 5 * rng.random(m.sum())

    # Descent: 70-100 km/h
    m = _phase_mask(t_s, CLIMB_END, DESC_END)
    speed[m] = 85 + 12 * np.sin(2 * np.pi * 0.008 * t_s[m]) + 5 * rng.random(m.sum())

    # Highway return: 110-130 km/h
    m = _phase_mask(t_s, DESC_END, DURATION_S + 1)
    speed[m] = 120 + 8 * np.sin(2 * np.pi * 0.005 * t_s[m]) + 3 * rng.random(m.sum())

    speed = _smooth(np.clip(speed, 0, 160), window=201)

    # ---- Coolant Temperature (°C) ----
    # Thermal model: temperature is driven by engine load (RPM * throttle)
    # with cooling proportional to vehicle speed (ram air)
    coolant = np.zeros(N_POINTS)
    coolant[0] = 40.0  # cold start
    dt = DURATION_S / N_POINTS

    for i in range(1, N_POINTS):
        # Heat input proportional to RPM (normalized)
        heat_in = (rpm[i] / 6000) * 0.15
        # Cooling proportional to speed (ram air) + base radiator cooling
        cooling = 0.02 + (speed[i] / 200) * 0.08
        # Thermal target based on heat balance
        target = 60 + (heat_in / (cooling + 0.01)) * 30
        target = min(target, 118)
        # First-order lag toward target (tau ~ 120s for heating, 90s for cooling)
        tau = 120 if target > coolant[i - 1] else 90
        alpha = dt / tau
        coolant[i] = coolant[i - 1] + alpha * (target - coolant[i - 1])

    coolant += rng.normal(0, 0.15, N_POINTS)
    coolant = _smooth(np.clip(coolant, 35, 120), window=201)

    # ---- Oil Temperature (°C) ----
    # Follows coolant with ~60s thermal lag, offset slightly lower
    lag_samples = int(60 * SAMPLE_RATE_HZ)
    oil_temp = np.zeros(N_POINTS)
    oil_temp[0] = 35.0
    for i in range(1, N_POINTS):
        # Target is lagged coolant minus small offset
        src_idx = max(0, i - lag_samples)
        target = coolant[src_idx] - 3
        tau = 150  # slower thermal mass
        alpha = dt / tau
        oil_temp[i] = oil_temp[i - 1] + alpha * (target - oil_temp[i - 1])

    oil_temp += rng.normal(0, 0.1, N_POINTS)
    oil_temp = _smooth(np.clip(oil_temp, 30, 120), window=201)

    # ---- Throttle Position (%) ----
    throttle = np.zeros(N_POINTS)
    m = _phase_mask(t_s, 0, CITY_END)
    throttle[m] = 15 + 10 * np.abs(np.sin(2 * np.pi * 0.02 * t_s[m])) + 5 * rng.random(m.sum())

    m = _phase_mask(t_s, CITY_END, HWY1_END)
    throttle[m] = 30 + 8 * np.sin(2 * np.pi * 0.008 * t_s[m]) + 3 * rng.random(m.sum())

    m = _phase_mask(t_s, HWY1_END, CLIMB_END)
    throttle[m] = 75 + 15 * np.sin(2 * np.pi * 0.03 * t_s[m]) + 5 * rng.random(m.sum())

    m = _phase_mask(t_s, CLIMB_END, DESC_END)
    throttle[m] = 10 + 8 * np.sin(2 * np.pi * 0.01 * t_s[m]) + 3 * rng.random(m.sum())

    m = _phase_mask(t_s, DESC_END, DURATION_S + 1)
    throttle[m] = 30 + 8 * np.sin(2 * np.pi * 0.008 * t_s[m]) + 3 * rng.random(m.sum())

    throttle = _smooth(np.clip(throttle, 0, 100), window=101)

    # ---- Intake Pressure (kPa) ----
    # Correlated with RPM and throttle: high load = high pressure
    intake = 30 + (rpm / 6000) * 50 + (throttle / 100) * 30
    intake += rng.normal(0, 1.5, N_POINTS)
    intake = _smooth(np.clip(intake, 20, 120), window=51)

    # ---- Engine Load (%) ----
    # Computed from RPM and throttle: load = f(RPM, throttle)
    # Spikes dramatically during mountain climb — the "smoking gun"
    engine_load = (rpm / 6000) * 0.55 + (throttle / 100) * 0.45
    engine_load = engine_load * 100  # scale to 0-100%
    engine_load += rng.normal(0, 1.0, N_POINTS)
    engine_load = _smooth(np.clip(engine_load, 0, 100), window=101)

    return {
        1: rpm,
        2: speed,
        3: coolant,
        4: oil_temp,
        5: throttle,
        6: intake,
        7: engine_load,
    }


def to_rle(values: np.ndarray, t_ns: np.ndarray, tolerance: float = 0.01) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compress raw samples to RLE format.

    Merges consecutive samples whose value changes by less than `tolerance`
    into single intervals [tstart, tend).
    """
    n = len(values)
    if n == 0:
        return np.array([]), np.array([]), np.array([])

    # Quantize to reduce noise-driven splits
    quantized = np.round(values / tolerance) * tolerance

    # Find change points
    changes = np.where(np.diff(quantized) != 0)[0] + 1
    starts = np.concatenate([[0], changes])
    ends = np.concatenate([changes, [n]])

    tstart = t_ns[starts]
    # tend = start of next interval (or end timestamp for last)
    tend_idx = np.minimum(ends, n - 1)
    tend = t_ns[tend_idx]
    # Use mean value per RLE segment
    rle_values = np.array([values[s:e].mean() for s, e in zip(starts, ends)])

    return tstart, tend, rle_values


def run():
    print("Connecting to Databricks...")
    w = WorkspaceClient(profile="fe-vm-maximhammer")

    # Find a warehouse
    warehouses = list(w.warehouses.list())
    wh = next((wh for wh in warehouses if wh.state.value == "RUNNING"), None)
    if not wh:
        # Start the serverless one
        wh = next(wh for wh in warehouses if "serverless" in (wh.name or "").lower() or "starter" in (wh.name or "").lower())
        print(f"Starting warehouse {wh.name}...")
        w.warehouses.start(wh.id)
        import time
        for _ in range(60):
            wh = w.warehouses.get(wh.id)
            if wh.state.value == "RUNNING":
                break
            time.sleep(5)
    print(f"Using warehouse: {wh.name} ({wh.id})")

    wh_id = wh.id

    def sql(query: str):
        result = w.statement_execution.execute_statement(
            warehouse_id=wh_id, statement=query, wait_timeout="50s"
        )
        if result.status and result.status.error:
            raise RuntimeError(f"SQL error: {result.status.error.message}")
        return result

    # ---- Create schema ----
    print(f"Creating schema {CATALOG}.{SCHEMA}...")
    sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

    # ---- Generate signals ----
    print("Generating synthetic signals...")
    rng = np.random.default_rng(42)
    signals = generate_signals(rng)

    t_ns = np.linspace(START_NS, END_NS, N_POINTS, dtype=np.int64)
    dt_s = DURATION_S / N_POINTS

    # ---- Convert to RLE and build SQL inserts ----
    print("Converting to RLE format...")

    # Collect per-channel data
    channel_rows = []  # (container_id, channel_id, tstart, tend, value)
    metrics_rows = []
    tag_rows = []

    for sig in SIGNALS:
        cid = sig["channel_id"]
        values = signals[cid]

        # RLE compression (tolerance varies by signal type)
        tol = {1: 5.0, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5, 6: 0.5, 7: 0.5}[cid]
        tstart, tend, rle_vals = to_rle(values, t_ns, tolerance=tol)

        print(f"  {sig['channel_name']}: {len(values)} raw → {len(rle_vals)} RLE segments")

        for ts, te, v in zip(tstart, tend, rle_vals):
            channel_rows.append((CONTAINER_ID, cid, int(ts), int(te), float(v)))

        # Metrics
        begin_ms = START_EPOCH_MS
        end_ms = START_EPOCH_MS + DURATION_S * 1000
        metrics_rows.append((
            CONTAINER_ID, cid, len(rle_vals),
            float(np.min(values)), float(np.max(values)), float(np.mean(values)),
            begin_ms, end_ms, DURATION_S * 1000,
            float(SAMPLE_RATE_HZ), "DOUBLE"
        ))

        # Tags
        tag_rows.append((CONTAINER_ID, cid, "channel_name", sig["channel_name"]))
        tag_rows.append((CONTAINER_ID, cid, "unit", sig["unit"]))

    # ---- Write tables via SQL INSERT ----
    # Drop and recreate tables
    tables = ["channels", "channel_metrics", "channel_tags", "container_metrics", "container_tags"]
    for t in tables:
        sql(f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA}.{t}")

    print("Creating tables...")

    sql(f"""CREATE TABLE {CATALOG}.{SCHEMA}.channels (
        container_id BIGINT, channel_id INT,
        tstart BIGINT, tend BIGINT, value DOUBLE
    ) CLUSTER BY (container_id, channel_id)""")

    sql(f"""CREATE TABLE {CATALOG}.{SCHEMA}.channel_metrics (
        container_id BIGINT, channel_id INT,
        sample_count INT, min DOUBLE, max DOUBLE, mean DOUBLE,
        begin_ms BIGINT, end_ms BIGINT, duration_ms BIGINT,
        sample_rate DOUBLE, value_type STRING
    ) CLUSTER BY (container_id, channel_id)""")

    sql(f"""CREATE TABLE {CATALOG}.{SCHEMA}.channel_tags (
        container_id BIGINT, channel_id INT,
        key STRING, value STRING
    ) CLUSTER BY (container_id, channel_id)""")

    sql(f"""CREATE TABLE {CATALOG}.{SCHEMA}.container_metrics (
        container_id BIGINT, vehicle_key STRING,
        start_ts BIGINT, stop_ts BIGINT,
        start_dt TIMESTAMP, stop_dt TIMESTAMP,
        duration_ms INT, num_channels INT
    ) CLUSTER BY (container_id)""")

    sql(f"""CREATE TABLE {CATALOG}.{SCHEMA}.container_tags (
        container_id BIGINT, key STRING, value STRING
    ) CLUSTER BY (container_id)""")

    # ---- Insert container_metrics ----
    print("Inserting container_metrics...")
    end_epoch_ms = START_EPOCH_MS + DURATION_S * 1000
    sql(f"""INSERT INTO {CATALOG}.{SCHEMA}.container_metrics VALUES (
        {CONTAINER_ID}, '{VEHICLE_KEY}',
        {START_EPOCH_MS}, {end_epoch_ms},
        TIMESTAMP '{_epoch_ms_to_ts(START_EPOCH_MS)}',
        TIMESTAMP '{_epoch_ms_to_ts(end_epoch_ms)}',
        {DURATION_S * 1000}, {len(SIGNALS)}
    )""")

    # ---- Insert container_tags ----
    print("Inserting container_tags...")
    ctags = [
        (CONTAINER_ID, "filename", "2025-07-22_VW_Golf_GTI_Alpine_Loop.mf4"),
        (CONTAINER_ID, "vehicle_key", VEHICLE_KEY),
        (CONTAINER_ID, "brand", "VW"),
        (CONTAINER_ID, "model", "Golf GTI"),
        (CONTAINER_ID, "from_city", "Garmisch-Partenkirchen"),
        (CONTAINER_ID, "to_city", "Garmisch-Partenkirchen"),
        (CONTAINER_ID, "condition", "Hot Weather Cooling Validation"),
        (CONTAINER_ID, "experiment_id", "cooling_validation_001"),
    ]
    values = ", ".join(f"({c}, '{k}', '{v}')" for c, k, v in ctags)
    sql(f"INSERT INTO {CATALOG}.{SCHEMA}.container_tags VALUES {values}")

    # ---- Insert channel_tags ----
    print("Inserting channel_tags...")
    values = ", ".join(
        f"({cid}, {chid}, '{k}', '{v}')" for cid, chid, k, v in tag_rows
    )
    sql(f"INSERT INTO {CATALOG}.{SCHEMA}.channel_tags VALUES {values}")

    # ---- Insert channel_metrics ----
    print("Inserting channel_metrics...")
    values = ", ".join(
        f"({cid}, {chid}, {sc}, {mn}, {mx}, {me}, {bms}, {ems}, {dms}, {sr}, '{vt}')"
        for cid, chid, sc, mn, mx, me, bms, ems, dms, sr, vt in metrics_rows
    )
    sql(f"INSERT INTO {CATALOG}.{SCHEMA}.channel_metrics VALUES {values}")

    # ---- Insert channels (RLE data) — batch to avoid SQL size limits ----
    print(f"Inserting {len(channel_rows)} RLE rows into channels table...")
    BATCH_SIZE = 5000
    for batch_start in range(0, len(channel_rows), BATCH_SIZE):
        batch = channel_rows[batch_start : batch_start + BATCH_SIZE]
        values = ", ".join(
            f"({cid}, {chid}, {ts}, {te}, {v})"
            for cid, chid, ts, te, v in batch
        )
        sql(f"INSERT INTO {CATALOG}.{SCHEMA}.channels VALUES {values}")
        done = min(batch_start + BATCH_SIZE, len(channel_rows))
        print(f"  ... {done}/{len(channel_rows)} rows inserted")

    print("\nDone! Data written to:")
    print(f"  {CATALOG}.{SCHEMA}.channels")
    print(f"  {CATALOG}.{SCHEMA}.channel_metrics")
    print(f"  {CATALOG}.{SCHEMA}.channel_tags")
    print(f"  {CATALOG}.{SCHEMA}.container_metrics")
    print(f"  {CATALOG}.{SCHEMA}.container_tags")
    print(f"\nTotal RLE rows: {len(channel_rows)}")
    print(f"Container ID: {CONTAINER_ID}")
    print(f"Vehicle: {VEHICLE_KEY}")


def _epoch_ms_to_ts(epoch_ms: int) -> str:
    """Convert epoch milliseconds to ISO timestamp string."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    run()
