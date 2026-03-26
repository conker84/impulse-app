# SampleSeries API Reference

Time series data as a sequence of samples with start times, end times, and values. Uses zero-order hold interpolation by default.

## Arithmetic Operations

All return `SampleSeries`. Can be applied between two signals or a signal and a constant.

| Operation | Example |
|---|---|
| `+` | `signal_a + signal_b`, `signal + 10` |
| `-` | `signal_a - signal_b`, `signal - offset` |
| `*` | `signal * 2`, `speed * 0.621371` |
| `/` | `signal_a / signal_b`, `signal / 100` |

## Comparison Operations

All return `Intervals` representing time periods where the condition is true.

| Operation | Example |
|---|---|
| `>` | `speed > 100` |
| `>=` | `temp >= 80` |
| `<` | `speed < 10` |
| `<=` | `temp <= 0` |
| `==` | `gear == 3` |
| `!=` | `state != 0` |

## Filtering

### `where(other)` → SampleSeries or PitSeries
Filters the series based on intervals or points in time.
- If `other` is `Intervals` → returns `SampleSeries` (only values during those intervals)
- If `other` is `PointsInTime` → returns `PitSeries` (values at those time points)

```python
speed_while_braking = speed.where(brake > 50)
temp_at_events = temp.where(engine_stop_events)
```

## Event Detection

### `rising_edges()` / `rising_edge()` → PointsInTime
Points where the value increases compared to the previous value.

### `falling_edges()` / `falling_edge()` → PointsInTime
Points where the value decreases compared to the previous value.

### `change_points(from_state, to_state)` → PointsInTime
Points where the signal transitions from `from_state` to `to_state`.

```python
gear_shift_1_to_2 = gear.change_points(from_state=1, to_state=2)
```

### `change_points_from_arbitrary_state_gt(to_state)` → PointsInTime
Points where the signal transitions from any state greater than `to_state` to `to_state`.

### `change_points_from_arbitrary_state_lt(to_state)` → PointsInTime
Points where the signal transitions from any state less than `to_state` to `to_state`.

### `change_points_to_arbitrary_state_gt(from_state)` → PointsInTime
Points where the signal transitions from `from_state` to any state greater than `from_state`.

### `change_points_to_arbitrary_state_lt(from_state)` → PointsInTime
Points where the signal transitions from `from_state` to any state less than `from_state`.

## Aggregation

### `max()` → float
Maximum value in the series (NaN if empty).

### `min()` → float
Minimum value in the series (NaN if empty).

### `mean()` → float
Weighted mean of values, weighted by interval durations (NaN if empty).

### `sum()` → float
Weighted sum of all values, weighted by interval durations (NaN if empty).

## Aggregation Within Intervals

All return `SampleSeries` with interval boundaries from the input and aggregated values.

### `max_within_intervals(intervals)` → SampleSeries
Maximum value within each interval.

### `min_within_intervals(intervals)` → SampleSeries
Minimum value within each interval.

### `mean_within_intervals(intervals)` → SampleSeries
Mean value within each interval.

```python
max_speed_per_phase = speed.max_within_intervals(driving_phases)
```

## Calculus

### `cumtrapz(cum_across_uncontinuous_intervals=True)` → SampleSeries
Cumulative integration using the trapezoidal rule.

```python
distance = speed.resample(1e8).cumtrapz()
```

### `trapz()` → float
Definite integration using the trapezoidal rule.

### `diff()` → SampleSeries
First discrete difference. Prepends with zero to maintain length. For derivatives, resample first.

```python
acceleration = speed.resample(0.01).diff()
```

## Resampling

### `resample(sample_rate=1.0, interp_kind='previous')` → SampleSeries
Resamples the series at the specified rate (in seconds).

```python
resampled = signal.resample(sample_rate=0.1)  # 10 Hz
```

## Transforms

### `abs()` → SampleSeries
Absolute values.

### `exp()` → SampleSeries
Exponential of values.

## Synchronization

### `synchronized(other)` → (SampleSeries, SampleSeries)
Aligns two series to overlapping time intervals.

### `synchronized_all(others)` → List[SampleSeries]
Aligns this series with multiple other series.

## Metadata

| Method | Returns | Description |
|---|---|---|
| `sample_count()` | int | Number of samples |
| `sample_rate()` | float | Average sample rate |
| `duration_ms()` | float | Total duration in milliseconds |
| `durations()` | ndarray | Duration of each sample interval |
| `start_time()` | float | Start time of first sample |
| `end_time()` | float | End time of last sample |
| `nan_ratio()` | float | Ratio of NaN values to total |

## Histograms

### `histogram(bins, weights, max_duration, ...)` → (ndarray, ndarray)
1D histogram of values, weighted by duration by default.

### `histogram2d(y_series, x_bins, y_bins, weights, max_duration)` → (ndarray, ndarray, ndarray)
2D histogram against another SampleSeries.

### `histogram3d(y_series, z_series, x_bins, y_bins, z_bins, weights, max_duration)` → (ndarray, list)
3D histogram against two other SampleSeries.
