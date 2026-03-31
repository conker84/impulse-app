# Statistics Aggregation — Detailed Reference

Statistics aggregations compute summary metrics (min, max, mean, median, std, count) across one or more signals. They provide a quick overview without the granularity of histograms.

## Constructor

```python
Statistics(
    name="temp_overview_p1",
    signal_refs=["coolant_temp", "oil_temp", "exhaust_temp"],
    stat_labels=["min", "max", "mean", "median", "std", "count"],
    desc="Temperature signal overview"
)
```

## Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique aggregation ID |
| `signal_refs` | list[str] | Yes | List of signal var_names to compute stats for |
| `stat_labels` | list[str] | No | Which statistics to compute (default: all six) |
| `event_signal_ref` | str | No | var_name of event signal for point-in-time statistics |
| `desc` | str | No | Human-readable description |

## Available Statistics

| Label | Description |
|---|---|
| `min` | Minimum value across all samples/sessions |
| `max` | Maximum value across all samples/sessions |
| `mean` | Arithmetic mean |
| `median` | Median (50th percentile) |
| `std` | Standard deviation |
| `count` | Number of samples |

## Signal Type Compatibility

Statistics can be computed on any signal type:
- **SampleSeries** — Stats computed over all sample values
- **Intervals** — Stats computed over interval durations
- **PointsInTime** — Count of events
- **PitSeries** — Stats computed over values at points in time

## Use Cases

### Quick signal overview
```python
# Overview of all temperature signals
Statistics(
    name="temp_stats_p1",
    signal_refs=["coolant_temp", "oil_temp", "exhaust_temp", "ambient_temp"],
    stat_labels=["min", "max", "mean"],
    desc="Temperature overview across all signals"
)
```

### Event-based statistics
```python
# Temperature at engine start events
Statistics(
    name="start_temp_stats_p1",
    signal_refs=["coolant_temp", "oil_temp"],
    stat_labels=["min", "max", "mean", "count"],
    event_signal_ref="engine_start_events",
    desc="Temperatures at engine start"
)
```

### Multi-signal comparison
```python
# Compare wheel speeds for imbalance detection
Statistics(
    name="wheel_speed_stats_p1",
    signal_refs=["whl_spd_fl", "whl_spd_fr", "whl_spd_rl", "whl_spd_rr"],
    stat_labels=["min", "max", "mean", "std"],
    desc="Wheel speed comparison"
)
```

## When to Use Statistics vs. Histograms

| Scenario | Recommendation |
|---|---|
| "What's the max temperature?" | Statistics |
| "How is the temperature distributed?" | 1D Histogram |
| "Quick overview of multiple signals" | Statistics |
| "Detailed analysis of one signal" | 1D Histogram |
| "How do two signals correlate?" | 2D Histogram |
| "Compare signals across vehicles" | Statistics + per-vehicle filtering |

## Persistence

Statistics results are stored in the gold layer alongside histogram results. Each statistic (min, max, mean, etc.) is stored as a separate row per signal per session, enabling cross-session aggregation.
