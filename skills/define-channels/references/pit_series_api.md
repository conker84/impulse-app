# PitSeries API Reference

Points in time with associated values. Produced when filtering a SampleSeries by PointsInTime (e.g. `signal.where(events)`).

## Creating PitSeries

```python
# From filtering a SampleSeries at specific time points
temp_at_events = temperature.where(engine_stop_events)  # → PitSeries

# Empty
empty = PitSeries.empty()
```

## Aggregation

### `max()` → float
Maximum value (NaN if empty).

### `min()` → float
Minimum value (NaN if empty).

### `abs()` → PitSeries
Absolute values.

## Histograms

### `histogram(bins, weight_const)` → (ndarray, ndarray)
1D histogram of values.

### `histogram2d(y_series, x_bins, y_bins, weights)` → tuple
2D histogram against another series.

### `histogram3d(y_series, z_series, x_bins, y_bins, z_bins, weights)` → tuple
3D histogram against two other series.

## Synchronization

### `synchronized(other)` → (PitSeries, PitSeries)
Synchronizes with another PitSeries or SampleSeries.
