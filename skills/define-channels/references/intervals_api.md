# Intervals API Reference

A collection of time intervals, each defined by a start time and an end time. Typically produced by comparison operations on signals (e.g. `speed > 100`).

## Creating Intervals

```python
# From comparison operations on SampleSeries
high_speed = speed > 100           # Intervals where speed > 100
is_running = engine_speed > 0      # Intervals where engine is running

# Combining with logical operators
fast_and_braking = (speed > 80) & (brake > 50)

# From PointsInTime
intervals = points.flipflop(reset_points)
intervals = points.expand(width=5.0)

# Empty
empty = Intervals.empty()
```

## Expanding / Shrinking

### `expand(width)` → Intervals
Extends all intervals by `width` seconds in both directions. Merges overlaps.

### `expand_left(width)` → Intervals
Extends start times backward by `width`. Merges overlaps.

### `expand_right(width)` → Intervals
Extends end times forward by `width`. Merges overlaps.

### `shrink(width)` → Intervals
Reduces intervals by `width` from both sides. Removes intervals that become empty.

### `shrink_left(width)` → Intervals
Increases start times by `width`. Removes empty intervals.

### `shrink_right(width)` → Intervals
Decreases end times by `width`. Removes empty intervals.

### `delay(amount)` → Intervals
Shifts all intervals by `amount` seconds (positive = forward, negative = backward).

## Filtering

### `filter(obj, inverse=False)` → Intervals
Returns intervals that overlap with `obj` (Intervals or PointsInTime). With `inverse=True`, returns non-overlapping intervals.

### `filter_first_intersection(obj)` → Intervals
Like `filter`, but keeps only the first interval that intersects each interval in `obj`.

### `filter_intersection_left(obj)` → Intervals
Returns intervals starting at overlap points and ending at original end times.

### `filter_intersection_right(obj)` → Intervals
Returns intervals starting at original start times and ending at overlap endpoints.

### `merge_overlaps(inplace=False)` → Intervals
Merges overlapping and consecutive intervals.

```python
merged = intervals.merge_overlaps()
```

## Accessors

| Method | Returns | Description |
|---|---|---|
| `start_points()` | PointsInTime | All start times as PointsInTime |
| `end_points()` | PointsInTime | All end times as PointsInTime |
| `starts()` | ndarray | Array of start times |
| `ends()` | ndarray | Array of end times |
| `start_time()` | float | Start time of first interval |
| `end_time()` | float | End time of last interval |
| `durations()` | ndarray | Duration of each interval |
| `duration_ms()` | float | Total duration in milliseconds |

## Histogram

### `histogram(bins, weight_const)` → (ndarray, ndarray)
Histogram of interval durations.

```python
hist, bins = intervals.histogram(bins=[0, 2, 4, 6])
```
