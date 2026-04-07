# Time Series Explorer Revamp — Project Plan

## Overview

Revamp the "Explore Time Series" section of the Impulse app to support interactive visualization of extremely large datasets (100M–300M+ data points) with dynamic zoom/pan re-aggregation, multi-signal overlay for correlation analysis, and smart dual-axis handling for signals with different units.

**Scope:** Only the Time Series Explorer (entered via "Explore Time Series" on the landing screen). NOT the report output visualization flow.

## Design Decisions

### Why Not Dash / Plotly Resampler?

The article ([Visualizing a Billion Points](https://medium.com/dbsql-sme-engineering/visualizing-a-billion-points-databricks-plotly-dash-and-the-plotly-resampler-45461bc3f466)) uses Plotly Dash + Plotly Resampler. We deliberately chose a different path:

1. **The app is FastAPI + React.** Dash is a separate web framework (Flask-based). Embedding it means two frameworks, two routing systems, two component libraries in one process. The time series section would feel like a foreign iframe.
2. **Dash adds nothing we can't do ourselves.** Strip away the framework, and Resampler does three things: stores data server-side (our Polars cache), listens for zoom/pan events (our React `onRelayout`), and runs LTTB (our `tsdownsample` calls). We already have all three pieces.
3. **UI consistency.** Dash components (buttons, dropdowns) look and behave differently from our React UI. Users would notice the seam.
4. **Auth is already solved.** The OBO token flow (`X-Forwarded-Access-Token`) works in our FastAPI routes. Wiring it through Dash callbacks adds fragile plumbing.
5. **Memory budget.** The 6–12 GB app memory should go to data, not framework overhead (~15 MB for Dash + dependencies).

The "magic" is `tsdownsample` (the Rust-based LTTB library) and Polars (fast in-memory DataFrames), not the Dash framework.

### Visual Style: Single Overlaid Chart (Article Figure 8)

Chose the single large chart with overlaid `scattergl` traces because:
- **Best for correlation** — the primary goal ("understand how signals move together")
- **Maximizes chart area** — no vertical space lost to subplot stacking
- **Proven at scale** — the article shows 24 traces with 1M points each in this layout

Navigation uses standard Plotly interactions (box-zoom, scroll-zoom, pan, double-click reset) rather than the article's dual coarse+dynamic chart pattern (Figure 6). Simpler, takes no extra vertical space, same user experience.

### Multi-Unit Axis Strategy

Learned from the article's Figure 8: they use dual y-axes with smart grouping — most signals share the left axis, outlier-range signals go to the right axis. Hover always shows the correct value.

Our approach:
- **Auto dual-axis (default):** Group signals into 2 clusters by unit + value range. Left y-axis gets the majority group, right y-axis gets the rest. Hover tooltip always shows actual value + unit.
- **Normalized mode (toggle):** All signals min-max scaled to [0, 1]. Single y-axis. Hover shows real value: `Signal: 42.5 C (normalized: 0.73)`. Best for pure correlation when magnitudes differ wildly.
- Grouping uses `min`/`max` from `channel_metrics` (already fetched in signal listing).

### Data Transport: Direct SQL Connector, Not MCP

The current `execute_sql` via MCP serializes every row as JSON text through the MCP protocol — unusable for 300M rows. The new data path uses `databricks-sql-connector` with Arrow-native result fetching, zero-copy into Polars. Metadata queries (containers, signals) stay on the existing MCP path since they return small result sets.

### In-Memory Polars Cache, Not Parquet/Volume

The article caches to Parquet files. We cache in-memory (Polars DataFrames) because:
- Parquet write + SQL re-read adds latency on both ends
- Data is already persisted in Delta Lake — no need for a second copy
- In-memory LTTB resampling is <50ms for any window on 300M points
- 12 GB app memory (large instance) supports multiple loaded channels

---

## High-Level Architecture

```
                         ┌──────────────────────────────────────┐
                         │   React Frontend (Plotly.js scattergl)│
                         │                                      │
                         │  Signal selector ──► "Load & Explore"│
                         │       │                              │
                         │  Zoom/Pan ──► POST /resample (~50ms) │
                         └────────────┬─────────────────────────┘
                                      │ REST API
                         ┌────────────▼─────────────────────────┐
                         │   FastAPI Backend                     │
                         │                                      │
                         │  ┌─ timeseries routes ─────────────┐ │
                         │  │ GET  /containers (metadata, MCP) │ │
                         │  │ GET  /signals    (metadata, MCP) │ │
                         │  │ POST /load       (fetch → cache) │ │
                         │  │ POST /resample   (LTTB → JSON)  │ │
                         │  └──────────────────────────────────┘ │
                         │                                      │
                         │  ┌─ ts_cache.py (Polars engine) ───┐ │
                         │  │ In-memory Polars DataFrames      │ │
                         │  │ Vectorized RLE expansion         │ │
                         │  │ tsdownsample LTTB on any window  │ │
                         │  │ LRU eviction by memory pressure  │ │
                         │  └──────────────────────────────────┘ │
                         │                                      │
                         │  ┌─ ts_connector.py ────────────────┐ │
                         │  │ databricks-sql-connector          │ │
                         │  │ Arrow-native fetch → Polars       │ │
                         │  │ OBO token auth                    │ │
                         │  └──────────────────────────────────┘ │
                         └────────────┬─────────────────────────┘
                                      │ DBSQL Protocol (Arrow)
                         ┌────────────▼─────────────────────────┐
                         │   Databricks SQL Warehouse            │
                         │   {catalog}.{schema}.channels (RLE)   │
                         │   300M+ rows per container             │
                         └──────────────────────────────────────┘
```

### Data Flow

1. **Select:** User picks catalog → schema → container → signals (checkboxes)
2. **Load:** `POST /load` → `databricks-sql-connector` fetches RLE rows as Arrow → zero-copy into Polars DataFrame → vectorized RLE expansion → numpy arrays cached in memory. This is the slow step (~10–60s for 300M rows).
3. **Render:** `POST /resample` with full range → LTTB downsamples to ~5,000 points per trace → JSON to frontend → Plotly `scattergl` renders
4. **Zoom:** User drags to select a time range → Plotly `relayout` event → debounced `POST /resample` with `x_min`/`x_max` → LTTB on just the visible window → chart updates with finer detail (~50ms round-trip)
5. **Reset:** Double-click → `POST /resample` with null range → back to full overview

---

## Implementation Plan

### Phase 1: Dependencies & Direct SQL Connector

**New dependencies** (add to `requirements.txt`):
- `databricks-sql-connector>=3.0.0` — Arrow-native DBSQL fetching
- `polars>=1.0.0` — in-memory DataFrame engine
- `pyarrow>=14.0.0` — Arrow interop between connector and Polars

(`tsdownsample` and `numpy` already present.)

**New file: `server/ts_connector.py`**

Thin wrapper around `databricks-sql-connector`:
- `get_connection(token: str)` — creates connection using OBO token + host/warehouse from `server.config`
  - Host from `get_workspace_client().config.host`
  - HTTP path from `WAREHOUSE_ID` → `/sql/1.0/warehouses/{id}`
  - `access_token=token` for OBO auth
  - Local dev fallback: uses CLI profile token
- `fetch_channel_polars(conn, catalog, schema, container_id, channel_id) -> pl.DataFrame`
  - Executes: `SELECT tstart, tend, value FROM {catalog}.{schema}.channels WHERE container_id = ? AND channel_id = ? ORDER BY tstart`
  - Uses `cursor.fetchall_arrow()` → `pl.from_arrow()` (zero-copy)
  - Returns DataFrame with columns `[tstart: Int64, tend: Int64, value: Float64]`

### Phase 2: In-Memory Cache Engine

**New file: `server/ts_cache.py`**

```
class ChannelData:
    cache_key: str               # "catalog.schema.container_id.channel_id"
    df: pl.DataFrame             # Raw RLE rows (tstart, tend, value)
    expanded_t: np.ndarray       # Step-pair timestamps (float64, nanoseconds)
    expanded_v: np.ndarray       # Step-pair values (float64)
    total_points: int            # len(expanded_t)
    t_min_ns: int                # First timestamp
    t_max_ns: int                # Last timestamp
    last_accessed: float         # time.monotonic() for LRU eviction

class TimeSeriesCache:
    _cache: dict[str, ChannelData]
    _max_memory_bytes: int       # Default 8 GB (configurable)

    load_channel(catalog, schema, container_id, channel_id, token) -> ChannelData
    resample(cache_key, x_min_ns, x_max_ns, n_points, normalize) -> dict
    is_loaded(cache_key) -> bool
    evict_lru() -> None
    get_memory_usage() -> int
```

**`load_channel` flow:**
1. Build cache key, check if already loaded (return immediately if so)
2. Open connection via `ts_connector.get_connection(token)`
3. Fetch all RLE rows → Polars DataFrame
4. Vectorized RLE expansion in Polars:
   ```python
   starts = df.select(col("tstart").alias("t"), col("value"))
   ends = df.filter(col("tend") != col("tstart")).select(col("tend").alias("t"), col("value"))
   expanded = pl.concat([starts, ends]).sort("t")
   ```
5. Extract numpy arrays: `expanded["t"].to_numpy()`, `expanded["value"].to_numpy()` (zero-copy)
6. Store as `ChannelData`, check memory, evict LRU if over threshold

**`resample` flow:**
1. Look up `ChannelData` by cache key
2. Binary-search `expanded_t` for window `[x_min_ns, x_max_ns]` → get slice indices
3. `tsdownsample.LTTBDownsampler().downsample(t_slice, v_slice, n_out=n_points)` → index array
4. If `normalize=True`: apply min-max scaling to values, include raw values in output
5. Convert timestamps ns → seconds, return as `[{t, v, v_raw?}, ...]`
6. Update `last_accessed` timestamp

### Phase 3: API Endpoints

**Modify: `server/routes/timeseries.py`**

Keep existing GET endpoints unchanged (containers, signals). Add:

**`POST /api/timeseries/load`**
```
Request:
  { "catalog": "...", "schema": "...",
    "container_id": 1, "channel_ids": [5, 12, 33] }

Response:
  { "channels": [
      { "channel_id": 5,  "cache_key": "cat.sch.1.5",
        "total_points": 45000000, "t_min_ns": ..., "t_max_ns": ...,
        "load_time_ms": 12400 },
      { "channel_id": 12, "cache_key": "cat.sch.1.12",
        "total_points": 82000000, "t_min_ns": ..., "t_max_ns": ...,
        "load_time_ms": 18200 },
      ...
    ],
    "memory_used_mb": 3200 }
```
- Loads each requested channel into the Polars cache
- If already cached, returns immediately with cached metadata
- This is the slow operation (~10–60s depending on data volume and warehouse size)

**`POST /api/timeseries/resample`**
```
Request:
  { "cache_keys": ["cat.sch.1.5", "cat.sch.1.12"],
    "x_min_ns": null, "x_max_ns": null,
    "n_points": 5000, "normalize": false }

Response:
  { "traces": [
      { "cache_key": "cat.sch.1.5", "channel_id": 5,
        "data": [{"t": 1.234, "v": 42.5}, ...],
        "total_points": 45000000,
        "window_points": 45000000 },
      { "cache_key": "cat.sch.1.12", "channel_id": 12,
        "data": [{"t": 1.234, "v": 7.1}, ...],
        "total_points": 82000000,
        "window_points": 82000000 }
    ] }
```
- Instant response (<50ms) — purely in-memory LTTB
- `x_min_ns` / `x_max_ns` = null means full range
- `window_points` = number of raw points in the current zoom window (for UI indicator)
- `normalize=true` returns min-max scaled values with `v_raw` field for hover

### Phase 4: Frontend — TimeSeriesView.tsx Rewrite

**Two-phase UX:**

1. **Selection phase** (mostly unchanged):
   Catalog → Schema → Container (radio) → Signals (checkbox multi-select)

2. **Load phase** (new):
   User clicks "Load & Explore" → calls `POST /load` → shows loading indicator with channel-by-channel status ("Loading Signal A... 45M points loaded") → once all channels are loaded, auto-calls `/resample` to render

3. **Explore phase** (enhanced):
   - Chart renders with `scattergl`, ~5,000 points per trace
   - Drag to select range → Plotly `relayout` fires → debounced (200ms) `POST /resample` with zoomed `x_min_ns`/`x_max_ns` → chart updates with finer detail
   - Double-click reset → `/resample` with null range → full overview
   - Scroll-wheel zoom supported

**Live data point counter (inspired by article Figure 8):**
- Prominently displayed above the chart: **"Currently viewing: 1,671,266 data points"**
- Updates on every zoom/pan — the `window_points` sum across all traces from the `/resample` response
- At full zoom-out shows total across all loaded signals
- Format: `Currently viewing: 1,671,266 data points (showing 5,000 per trace)`

**Smart axis assignment:**
- Frontend reads `unit`, `min_value`, `max_value` from each signal's metadata
- Groups signals into 2 clusters by unit + value range
- Cluster with more signals → left y-axis; other → right y-axis
- If 1 unit → single y-axis
- If exactly 2 units → one per axis

**Clear axis labeling (learned from article Figure 8):**
- Left y-axis title: unit name(s) for the signals assigned there, e.g., `"rpm"` or `"Temperature (°C), Pressure (bar)"`
- Right y-axis title: unit name(s) for secondary group, e.g., `"Voltage (V)"`
- Legend entries show axis assignment: `"EngineSpeed (rpm) [L]"` vs `"BatteryVoltage (V) [R]"`
- Both axis sets persist at all zoom levels — zooming never collapses to a single axis

**Hover behavior — progressive detail based on zoom level:**
- **Overview level** (`window_points > 10,000` per trace): basic hover showing signal name, approximate time, value, and unit. Template: `<b>EngineSpeed</b><br>2024-03-15 14:23<br>2,450 rpm`
- **Detail level** (`window_points <= 10,000` per trace): rich hover with precise timestamp (sub-second), exact value, unit, and which axis. Template: `<b>EngineSpeed</b><br>2024-03-15 14:23:07.342<br>2,450.73 rpm<br>Left axis`. Also enable `hovermode: "x unified"` so hovering shows values for ALL traces at that timestamp in a single tooltip — best for correlation analysis.
- The `/resample` response already includes `window_points` per trace; the frontend uses this to switch hover templates.
- With dual y-axes, hover must show the **correct** y-value for each trace (Plotly handles this natively when traces are assigned to `yaxis` vs `yaxis2`).

**Normalize toggle:**
- Button in chart header: `[Absolute | Normalized]`
- Switching calls `/resample` with `normalize=true/false`
- Normalized mode: single y-axis [0, 1], hover shows real values: `"EngineSpeed: 0.73 (2,450 rpm)"`
- Axis labels update to "Normalized [0–1]"

**Adding a signal while exploring:**
- If signal is already cached → just add trace, call `/resample` for the new channel
- If not cached → trigger `/load` for just that channel, then add to chart
- No full reload needed
- New signal auto-assigned to correct axis based on unit/range grouping

**Chart header bar:**
```
  Currently viewing: 127,000,000 data points (showing 5,000 per trace)
  Signals: EngineSpeed (rpm) [L], OilTemp (°C) [L]  |  Voltage (V) [R]    [Absolute ▾]  [Export CSV]
```

**New API functions** (add to `frontend/src/api.ts`):
- `loadTimeSeriesChannels(catalog, schema, containerId, channelIds)` → POST `/load`
- `resampleTimeSeries(cacheKeys, xMinNs, xMaxNs, nPoints, normalize)` → POST `/resample`

**New types** (add to `frontend/src/types.ts`):
- `TimeSeriesLoadResponse`
- `TimeSeriesResampleRequest` / `TimeSeriesResampleResponse`

### Phase 5: Testing Strategy

Testing uses a two-layer approach: local synthetic data for rapid UI iteration, then FEVM deploy for real-data validation.

**Layer 1 — Local with synthetic data (self-service, no user involvement):**

New file: `test/synthetic_ts.py` — generates realistic test data and pre-populates the cache:
- Multiple signal types: sine waves (rpm), step functions (gear), random walks (temperature), sawtooth (voltage)
- Different units and value ranges to exercise dual-axis grouping
- Configurable point counts (default 1M per signal for responsive local testing)
- Registers synthetic container/signals so the UI can discover and select them

The `/load` endpoint detects `container_id=0` as the synthetic marker and loads from the generator instead of the SQL connector. The rest of the pipeline (cache, resample, frontend) runs identically.

What this covers:
- [ ] Chart layout, axis labels, legend with [L]/[R] annotations
- [ ] Dual-axis grouping logic (signals with different units)
- [ ] Hover behavior at overview vs detail zoom levels
- [ ] "Currently viewing: X data points" counter updating on zoom
- [ ] Normalize toggle (absolute ↔ normalized)
- [ ] Signal add/remove without full reload
- [ ] Loading states and error handling
- [ ] Progressive hover (basic → rich when zoomed below 10k window points)
- [ ] Visual regression via `screencapture` after frontend rebuild

Testing loop: edit code → `npx tsc -b && npx vite build` → reload localhost:8001 → screenshot → verify.

**Layer 2 — FEVM deploy with real data (user validates):**

After the UI is visually solid locally, commit + deploy via `test/deploy-fevm.sh`. User tests with real 300M-row silver layer data.

What only real data can validate:
- [ ] `databricks-sql-connector` Arrow fetch with OBO token auth
- [ ] Load performance with 300M rows (target: <60s on medium warehouse)
- [ ] Memory pressure and LRU eviction under real load
- [ ] Real RLE data characteristics (gaps, irregular intervals, mixed sample rates)
- [ ] Resample latency with 300M cached points (target: <50ms)
- [ ] End-to-end zoom/pan cycle with warehouse-scale data

**Execution flow:**
```
1. Build backend (ts_connector, ts_cache, routes)
2. Build synthetic data generator
3. Build frontend rewrite
4. Local iteration: screenshot → fix → screenshot → fix (3-4 cycles)
5. Commit + deploy to FEVM
6. User tests with real 300M-row data
7. Fix issues from feedback → redeploy
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `requirements.txt` | Modify | Add `polars`, `databricks-sql-connector`, `pyarrow` |
| `server/ts_connector.py` | **New** | Direct SQL connector for Arrow-native data fetching |
| `server/ts_cache.py` | **New** | In-memory Polars cache + LTTB resample engine |
| `server/routes/timeseries.py` | Modify | Add `POST /load` and `POST /resample` endpoints; keep existing metadata GETs |
| `test/synthetic_ts.py` | **New** | Synthetic data generator for local testing |
| `frontend/src/components/TimeSeriesView.tsx` | Modify | Two-phase UX (load → explore), instant zoom/pan, dual-axis grouping, normalize toggle |
| `frontend/src/api.ts` | Modify | Add `loadTimeSeriesChannels()`, `resampleTimeSeries()` |
| `frontend/src/types.ts` | Modify | Add load/resample request/response types |
| `frontend/package.json` | No change | Already has `plotly.js-dist-min` and `react-plotly.js` |

---

## Architecture Section (for README)

> Paste this into the README under a new `### Time Series Explorer` subsection once implementation is complete.

```markdown
### Time Series Explorer

The "Explore Time Series" feature provides interactive visualization of massive time series
datasets (100M–300M+ data points) from the Impulse silver layer.

**Architecture:**
- **Data transport:** `databricks-sql-connector` fetches RLE channel data as Arrow batches
  from the SQL Warehouse, zero-copy into Polars DataFrames
- **In-memory cache:** Polars DataFrames hold expanded time series in server memory.
  LRU eviction keeps total usage within the app's memory budget (6–12 GB)
- **Dynamic resampling:** On every zoom/pan interaction, the LTTB algorithm
  (`tsdownsample`) downsamples the visible window to ~5,000 representative points
  in <50ms, preserving visual fidelity
- **Rendering:** Plotly.js `scattergl` (GPU-accelerated WebGL) renders overlaid traces
  with smart dual y-axis grouping for signals with different units

**User flow:**
1. Select catalog, schema, container, and signals
2. Click "Load & Explore" — data is fetched from the warehouse into server memory (10–60s)
3. Chart renders with full-range overview, live counter shows total data points in view
4. Drag to zoom into a region — chart re-aggregates instantly with finer detail
5. At high zoom levels (<10k points in view), hover switches to rich detail mode
   with precise timestamps, unified cross-trace tooltips, and axis identification
6. Double-click to reset to full range

**Key features:**
- Multi-signal overlay with automatic dual y-axis grouping by unit/value range
- Live "Currently viewing: X data points" counter that updates on every interaction
- Progressive hover: basic at overview level, rich with sub-second timestamps when zoomed in
- Clear axis labels and legend entries showing which signals map to which y-axis
- Optional normalized [0–1] view for comparing signals with wildly different scales
- Add/remove signals without reloading already-cached data
```

---

## Constraints & Assumptions

- **App memory:** 6 GB default, upgradeable to 12 GB (large instance). Each channel at 300M RLE rows ≈ 7.2 GB expanded. Practical limit: 1–2 large channels or many smaller ones simultaneously.
- **SQL Warehouse:** Must be running or auto-start enabled. Initial load time depends on warehouse size.
- **OBO token:** Used for all SQL queries. Token lifecycle is not handled in this phase.
- **Browser:** `scattergl` requires WebGL support (all modern browsers).
- **Fallback:** If `databricks-sql-connector` is unavailable (e.g., local dev without it installed), fall back to the existing MCP `execute_sql` path with the current 50k-point limit.
