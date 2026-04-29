# 1D Histogram Types — Detailed Reference

The framework uses a single `Histogram` class with an `agg_type` parameter to distinguish between histogram types.

## Histogram (Duration)

Measures how much **time** a signal spends in each value bin. The histogram is weighted by the duration of each sample interval.

**Input:** `base_expr` must evaluate to `SampleSeries`.

### Constructor

```python
Histogram(
    name="eng_spd_hist_p1",
    base_expr=signals["Eng_Spd_masked"],
    bins=[float(i) for i in range(0, 6000, 500)],
    desc="Distribution of engine speed over time",
    agg_type="duration",
    values_unit="nanoseconds",   # optional
    bins_unit="rpm"              # optional
)
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique histogram ID |
| `base_expr` | TimeSeriesExpression → SampleSeries | Yes | Signal to histogram |
| `bins` | list[float] | Yes | Bin edges in the unit of `base_expr` |
| `event` | Event | No | Event filter (BasicEvent or ContainerEvent) |
| `desc` | str | No | Human-readable description |
| `agg_type` | str | No | Type label: "duration", "distance", or "duration_count" |
| `signal_name` | str | No | Display name for the signal |
| `values_unit` | str | No | Unit for the values axis (typically `"nanoseconds"`) |
| `bins_unit` | str | No | Unit for the bins axis (e.g. `"rpm"`, `"°C"`) |

### When to use
- Analyzing how long a signal stays in specific ranges
- Engine speed distribution, temperature distribution, pressure distribution

### Examples

```python
# Basic engine speed duration histogram
hist = Histogram(
    name="eng_spd_hist_p1",
    base_expr=signals["Eng_Spd_masked"],
    bins=[float(i) for i in range(0, 6000, 500)],
    desc="Distribution of engine speed over time",
    agg_type="duration",
    bins_unit="rpm"
)

# Temperature histogram with catch-all bins
hist = Histogram(
    name="water_temp_hist_p2",
    base_expr=signals["coolant_temp"],
    bins=[-9999.0] + [float(i) for i in range(150, 360, 10)] + [9999.0],
    desc="Coolant temperature distribution",
    agg_type="duration",
    values_unit="nanoseconds",
    bins_unit="°C"
)

# Histogram of a filtered/derived signal
hist = Histogram(
    name="opf_temp_flipflop_p1",
    base_expr=signals["temp_opf_within_flipflop"],
    bins=[float(i) for i in range(0, 1000, 100)],
    desc="OPF temperature within flipflop intervals",
    agg_type="duration",
    bins_unit="°C"
)
```

---

## Histogram (Distance)

Measures how much **distance** is traveled while a signal is in each value bin.

**Input:** `base_expr` must evaluate to `SampleSeries`.

> **Required:** a cumulative-distance weight signal (`weights_expr`). The framework runs `diff()` on it internally to compute Δkm per sample. There is **no** implicit "auto-integrate vehicle_speed" — without `weights_expr` the constructor raises `TypeError`. Use the physical `odometer` channel when available, or define a virtual `distance_km` from vehicle speed (see below).

### Constructor

```python
HistogramDistance(
    name="eng_spd_hist_distance_p1",
    base_expr=signals["engine_speed"],
    weights_expr=signals["odometer"],   # cumulative km — REQUIRED
    bins=[float(i) for i in range(0, 6000, 500)],
    desc="Distribution of engine speed over driven distance",
    bins_unit="rpm",
    values_unit="km",
)
```

### When to use
- Analyzing signal distribution weighted by distance instead of time
- Understanding how far the vehicle drives at each speed, temperature, etc.

### Distance signal options
- **Preferred:** an odometer channel from the silver layer (already cumulative km).
- **Fallback (no odometer):** derive a virtual `distance_km` by integrating vehicle speed:

```python
veh_spd = query.channel(channel_name="vehicle_speed")
distance_km = (veh_spd.resample(1e8).cumtrapz() / 3600 / 1e9)
signals["distance_km"] = distance_km
```

---

## Histogram (Duration Count)

Counts how many **events** (intervals) fall into different **duration** bins. Analyzes the distribution of how long conditions last.

**Input:** `base_expr` must evaluate to `Intervals`.

### Constructor

```python
Histogram(
    name="warmup_duration_hist_p2",
    base_expr=signals["engine_warmup_intervals"],
    bins=[float(i) for i in np.arange(0, 210 * 1e9, 10 * 1e9)],
    desc="Distribution of engine warm-up event durations",
    agg_type="duration_count",
    values_unit="duration count",
    bins_unit="Duration [nanoseconds]"
)
```

### When to use
- Analyzing how long specific operating conditions last
- Cold start duration, heating phases, braking events

### Important
- Bins are in **nanoseconds** since interval durations are measured in nanoseconds.
- Use `np.arange()` for generating nanosecond bin edges: `np.arange(0, 210 * 1e9, 10 * 1e9)` = 0 to 200 seconds in 10-second steps.
- The `base_expr` must evaluate to `Intervals`, not `SampleSeries`.

### Examples

```python
# Duration of engine warm-up events
engine_warmup = (coolant_temp < 80) & (engine_running > 0.5) & (engine_speed > 500)
signals["engine_warmup"] = engine_warmup

hist = Histogram(
    name="warmup_duration_hist_p2",
    base_expr=signals["engine_warmup"],
    bins=[float(i) for i in np.arange(0, 210 * 1e9, 10 * 1e9)],
    desc="Distribution of engine warm-up event durations",
    agg_type="duration_count",
    values_unit="duration count",
    bins_unit="Duration [nanoseconds]"
)
```

---

## Persistence Schema

1D histograms are persisted in Unity Catalog using two tables:

### `histogram_dimension` (metadata)

| Column | Type | Description |
|---|---|---|
| `visual_id` | int | Primary key |
| `report_id` | int | Report identifier |
| `name` | string | Histogram name (matches constructor `name`) |
| `description` | string | Histogram description |
| `type` | string | Histogram type |
| `page_number` | int | Page where the histogram is displayed |
| `x_bins` | double[] | Bin edges |
| `x_bins_unit` | string | Bins unit |
| `x_expression` | string | Expression string |

### `histogram_fact` (per-session data)

| Column | Type | Description |
|---|---|---|
| `global_session_id` | string | Session identifier (FK) |
| `visual_id` | int | References histogram_dimension (FK) |
| `x_bin_id` | int | Bin index |
| `hist_value` | double | Histogram value for this bin and session |
| `x_lower_bound` | double | Lower bound of the bin |
| `x_upper_bound` | double | Upper bound of the bin |
| `x_bin_name` | string | Human-readable bin label |

The fact table stores one row per bin per session, allowing aggregation across sessions (e.g. `SUM(hist_value)` for total duration/count).
