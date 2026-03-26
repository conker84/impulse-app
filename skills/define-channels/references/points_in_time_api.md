# PointsInTime API Reference

A collection of discrete time points. Typically produced by event detection methods like `.rising_edges()`, `.falling_edges()`, or `.change_points()`.

## Creating PointsInTime

```python
# From event detection on SampleSeries
rising = signal.rising_edges()
falling = signal.falling_edges()
transitions = signal.change_points(from_state=0, to_state=1)

# Empty
empty = PointsInTime.empty()
```

## Expanding to Intervals

### `expand(width)` → Intervals
Expands each point into an interval centered on the point, extending `width` in both directions.

```python
windows = events.expand(5.0)  # 10-second windows centered on events
```

### `expand_left(width)` → Intervals
Each point becomes the end of an interval, extending `width` to the left.

### `expand_right(width)` → Intervals
Each point becomes the start of an interval, extending `width` to the right.

## Flipflop (Interval Creation)

### `flipflop(reset_points)` → Intervals
Creates intervals using a set/reset pattern:
- Each point in `self` opens a new interval (if not already open)
- The nearest point in `reset_points` closes it
- Dominant reset: if reset is before or equal to set, the interval is ignored

```python
engine_on = start_events.flipflop(stop_events)
```

## Filtering

### `filter(other, inverse=False)` → PointsInTime
Returns points that match points in `other`. With `inverse=True`, returns non-matching points.

### `filter_by_distance(min_dist)` → PointsInTime
Removes points that are closer than `min_dist` to the previous point.

```python
spaced_events = events.filter_by_distance(1.0)  # at least 1 second apart
```

### `filter_first_intersection(obj)` → PointsInTime
Keeps only the first point that intersects each interval in `obj`.

### `filter_intersection_left(other)` → PointsInTime
Intersection of two PointsInTime objects (alias for `&` operator).

### `intersection_filter_right(other)` → PointsInTime
Same as `filter_intersection_left` — intersection of two PointsInTime.

## Other

### `delay(amount)` → PointsInTime
Shifts all time points by `amount` seconds.
