# 1D Histogram Types — Detailed Reference

## HistogramDuration

Measures how much **time** a signal spends in each value bin. The histogram is weighted by the duration of each sample interval.

**Input:** `base_expr` must evaluate to `SampleSeries`.

### Constructor

```python
HistogramDuration(
    name="eng_spd_hist_p1",
    base_expr=signals["Eng_Spd_masked"],
    bins=[float(i) for i in range(0, 6000, 500)],
    max_duration=100 * 1e9,      # optional, nanoseconds
    desc="Distribution of engine speed over time",
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
| `max_duration` | float | No | Max sample duration in nanoseconds. Caps individual samples to prevent outlier inflation. |
| `desc` | str | No | Human-readable description |
| `values_unit` | str | No | Unit for the values axis (typically `"nanoseconds"`) |
| `bins_unit` | str | No | Unit for the bins axis (e.g. `"rpm"`, `"°C"`) |

### When to use
- Analyzing how long a signal stays in specific ranges
- Engine speed distribution, temperature distribution, pressure distribution

### Examples

```python
# Basic engine speed duration histogram
hist = HistogramDuration(
    name="eng_spd_hist_p1",
    base_expr=signals["Eng_Spd_masked"],
    bins=[float(i) for i in range(0, 6000, 500)],
    max_duration=100 * 1e9,
    desc="Distribution of engine speed over time",
    bins_unit="rpm"
)

# Temperature histogram with catch-all bins
hist = HistogramDuration(
    name="water_temp_hist_p2",
    base_expr=signals["F_OF_EA_Wasserpumpe_masked"],
    bins=[-9999.0] + [float(i) for i in range(150, 360, 10)] + [9999.0],
    max_duration=100 * 1e9,
    desc="Water pump temperature distribution",
    values_unit="nanoseconds",
    bins_unit="°C"
)

# Histogram of a filtered/derived signal
hist = HistogramDuration(
    name="opf_temp_flipflop_p1",
    base_expr=signals["temp_opf_within_flipflop"],
    bins=[float(i) for i in range(0, 1000, 100)],
    max_duration=100 * 1e9,
    desc="OPF temperature within flipflop intervals",
    bins_unit="°C"
)
```

---

## HistogramDistance

Measures how much **distance** is traveled while a signal is in each value bin. Instead of weighting by duration, it weights by a cumulative distance signal.

**Input:** `base_expr` and `weights_expr` must both evaluate to `SampleSeries`.

### Constructor

```python
HistogramDistance(
    name="eng_spd_hist_distance_p1",
    base_expr=signals["Eng_Spd_masked"],
    weights_expr=signals["distance_km"],
    bins=[float(i) for i in range(0, 6000, 500)],
    desc="Distribution of engine speed over driven distance",
    bins_unit="rpm"
)
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique histogram ID |
| `base_expr` | TimeSeriesExpression → SampleSeries | Yes | Signal to histogram |
| `weights_expr` | TimeSeriesExpression → SampleSeries | Yes | Cumulative distance signal (e.g. integrated vehicle speed) |
| `bins` | list[float] | Yes | Bin edges in the unit of `base_expr` |
| `desc` | str | No | Human-readable description |
| `bins_unit` | str | No | Unit for the bins axis |

### When to use
- Analyzing signal distribution weighted by distance instead of time
- Understanding how far the vehicle drives at each speed, temperature, etc.

### Examples

```python
# Engine speed weighted by driven distance
hist = HistogramDistance(
    name="eng_spd_hist_distance_p1",
    base_expr=signals["Eng_Spd_masked"],
    weights_expr=signals["distance_km"],
    bins=[float(i) for i in range(0, 6000, 500)],
    desc="Distribution of engine speed over driven distance",
    bins_unit="rpm"
)
```

### Distance signal definition
The distance signal is typically defined as the cumulative integral of vehicle speed:

```python
veh_spd = query.channel_with_alias(channel_alias_name="AL_Geschwindigkeit")
distance_km = (veh_spd.resample(1e8).cumtrapz() / 3600 / 1e9)
signals["distance_km"] = distance_km
```

---

## HistogramDurationCount

Counts how many **events** (intervals) fall into different **duration** bins. Analyzes the distribution of how long conditions last.

**Input:** `base_expr` must evaluate to `Intervals`.

### Constructor

```python
HistogramDurationCount(
    name="kaltstart_hist_p2",
    base_expr=signals["V_Katheizen_MotorGestartet_Drehzahl"],
    bins=[float(i) for i in np.arange(0, 210 * 1e9, 10 * 1e9)],
    weight_const=1.0,
    desc="Distribution of catalyst heating event durations",
    values_unit="duration count",
    bins_unit="Duration [nanoseconds]"
)
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique histogram ID |
| `base_expr` | TimeSeriesExpression → Intervals | Yes | Interval expression whose durations are histogrammed |
| `bins` | list[float] | Yes | Bin edges in **nanoseconds** (duration of intervals) |
| `weight_const` | float | No | Constant weight per event (typically `1.0`) |
| `desc` | str | No | Human-readable description |
| `values_unit` | str | No | Unit for the values axis (typically `"duration count"`) |
| `bins_unit` | str | No | Unit for the bins axis (typically `"Duration [nanoseconds]"`) |

### When to use
- Analyzing how long specific operating conditions last
- Cold start duration, heating phases, braking events

### Important
- Bins are in **nanoseconds** since interval durations are measured in nanoseconds.
- Use `np.arange()` for generating nanosecond bin edges: `np.arange(0, 210 * 1e9, 10 * 1e9)` = 0 to 200 seconds in 10-second steps.
- The `base_expr` must evaluate to `Intervals`, not `SampleSeries`. Intervals are typically created from comparison operations (e.g. `(signal > threshold) & (other_signal > threshold2)`).

### Examples

```python
# Duration of catalyst heating events
V_Katheizen = (B_kh > 0.5) & (B_stend > 0.5) & (Eng_Spd_masked > 500)
signals["V_Katheizen"] = V_Katheizen

hist = HistogramDurationCount(
    name="kaltstart_hist_p2",
    base_expr=signals["V_Katheizen"],
    bins=[float(i) for i in np.arange(0, 210 * 1e9, 10 * 1e9)],
    weight_const=1.0,
    desc="Distribution of catalyst heating event durations",
    values_unit="duration count",
    bins_unit="Duration [nanoseconds]"
)
```

---

## HistogramEventCount

Counts how many **events** occur at each **signal value**. Analyzes the distribution of a continuous signal at discrete event points.

**Input:** `base_expr` must evaluate to `SampleSeries`, `event_expr` must evaluate to `PointsInTime`.

### Constructor

```python
HistogramEventCount(
    name="tmp_opf_hist_p1",
    base_expr=signals["mean_temp_opf"],
    event_expr=signals["syc_stsub_rising_edges"],
    bins=[float(i) for i in range(0, 1000, 100)],
    weight_const=1.0,
    desc="OPF temperature distribution at engine stop events",
    values_unit="event count",
    bins_unit="°C"
)
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique histogram ID |
| `base_expr` | TimeSeriesExpression → SampleSeries | Yes | Signal whose value is sampled at event points |
| `event_expr` | TimeSeriesExpression → PointsInTime | Yes | Event trigger (discrete time points) |
| `bins` | list[float] | Yes | Bin edges in the unit of `base_expr` |
| `weight_const` | float | No | Constant weight per event (typically `1.0`) |
| `desc` | str | No | Human-readable description |
| `values_unit` | str | No | Unit for the values axis (typically `"event count"`) |
| `bins_unit` | str | No | Unit for the bins axis |

### When to use
- Analyzing signal values at specific events (e.g. temperature at engine start/stop)
- Counting how often a signal is in a certain range when an event occurs

### Important
- `event_expr` must evaluate to `PointsInTime` (e.g. from `.rising_edges()`, `.falling_edges()`, `.change_points()`)
- `base_expr` is evaluated at the event points to determine which bin to increment

### Examples

```python
# OPF temperature at engine stop events
SyC_stSub = query.channel(link_name="MRG3EVO", signal_name="SyC_stSub")
syc_rising = SyC_stSub.change_points(4, 5)
signals["syc_rising"] = syc_rising

hist = HistogramEventCount(
    name="tmp_opf_hist_p1",
    base_expr=signals["mean_temp_opf"],
    event_expr=signals["syc_rising"],
    bins=[float(i) for i in range(0, 1000, 100)],
    weight_const=1.0,
    desc="OPF temperature at engine stop",
    values_unit="event count",
    bins_unit="°C"
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

### `histogramNd_fact` (per-session data)

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
