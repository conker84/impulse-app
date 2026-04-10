---
name: define-channels
description: Define physical and virtual channels for an Impulse framework report. Includes automotive domain knowledge (EN/DE) for mapping problem descriptions to signal families. Use when the user wants to add signals or describes an analysis goal.
compatibility: Part of the Impulse app. Loaded on-demand during the Channels wizard step.
allowed-tools: add_physical_signal add_virtual_signal suggest_signal_candidates mcp_execute_sql load_skill
---

# Define Channels

Help the user define physical and virtual channels for an Impulse framework report. This skill is loaded on-demand by the LLM agent during the **Channels** wizard step of the Impulse app.

## Context

- The system prompt includes a **Currently Defined Signals** section listing all signals already added to the report. Use the exact `var_name` values when building virtual signal expressions.
- Physical signals are added through a two-step UI flow: SQL alias search followed by user selection from checkboxes.
- Virtual signals are added directly via the `add_virtual_signal` tool.
- The final `01_signal_definitions.py` code is auto-generated at deploy time — you do not edit files directly.

## Core Concepts

### Data Model

The query engine has four core data types. All methods available on these types can also be called on **TimeSeriesExpressions** that evaluate to the respective type.

| Type | Description | Produced by |
|---|---|---|
| **SampleSeries** | Time series with start times, end times, and values | `query.channel()`, arithmetic ops, `.where(Intervals)`, `.resample()` |
| **Intervals** | Time intervals (start/end pairs) | Comparison ops (`>`, `<`, `==`, etc.), `.flipflop()` |
| **PointsInTime** | Discrete time points | `.rising_edges()`, `.falling_edges()`, `.change_points()` |
| **PitSeries** | Points in time with associated values | `.where(PointsInTime)` |

### Checking Expression Types

Every `TimeSeriesExpression` has an `eval_type()` method that returns the data type the expression evaluates to. Use this to verify which methods from the API are available for a given expression:

```python
expr = query.channel(channel_name="Eng_Spd")
expr.eval_type()  # → SampleSeries

expr2 = expr > 1000
expr2.eval_type()  # → Intervals

expr3 = expr.rising_edges()
expr3.eval_type()  # → PointsInTime

expr4 = expr.where(expr3)
expr4.eval_type()  # → PitSeries
```

When building complex signal chains, use `eval_type()` to confirm the resulting type before applying further methods. For example, `.max_within_intervals()` is only available on SampleSeries, while `.flipflop()` is only available on PointsInTime.

### Expression Chain

Signals are built by chaining operations:

```
Physical Signal → Filter/Transform → Virtual Signal
query.channel() → .where() / arithmetic / .resample() → named signal
```

## Steps

### 1. Check currently defined signals

The system prompt includes a "Currently Defined Signals" section. Review it to understand which physical and virtual signals already exist before adding new ones. Use the exact `var_name` values when referencing signals in virtual expressions.

### 2. Understand user intent

The user may want to:
- **Add physical signals** — search for channel aliases and register them via the checkbox UI
- **Add virtual signals** — build derived signals from existing ones using arithmetic, comparisons, filtering, etc.
- **Look up a channel** — search for available channel aliases by keyword

### 3. Add physical signals

Physical signals are added through a two-step flow: first search for aliases via SQL, then present candidates to the user via `suggest_signal_candidates`. The user selects from the checkbox UI in the right panel. The generated code will use the QueryBuilder API:

```python
# By channel name and device name
signal = query.channel(channel_name="Eng_Spd", device_name="CAN")

# By channel tag (any tag key-value pair from channel_tags table)
signal = query.channel(channel_alias_name="AL_EngineSpeed")

# By channel alias (alias-based lookup)
signal = query.channel(channel_alias_name="EngineSpeed")
```

The keywords passed to `channel()` depend on the configured query solver and how signals are identified in the measurement database. Common patterns:
- `channel_name` + `device_name`
- `signal_name` + `link_name`
- `channel_alias_name` (for alias-based lookup)

### 3a. Channel Alias Lookup

When the user provides a descriptive name (e.g. "temperature", "speed", "torque") but doesn't know the exact alias, look up matching channels in the aliases table in Unity Catalog.

**Lookup table:** `<aliases_table>`

**Procedure:**

1. Query for matching aliases using a `LIKE` filter on the alias column:
   ```sql
   SELECT DISTINCT channel_alias_name
   FROM <aliases_table>
   WHERE channel_alias_name LIKE '%<user_keyword>%'
      OR channel_name LIKE '%<user_keyword>%'
   ORDER BY channel_alias_name
   LIMIT 50
   ```

2. Call `suggest_signal_candidates` with all result rows as `[{alias: "<channel_alias_name>"}]`. This renders interactive checkboxes in the right panel.

3. The user selects aliases from the checkbox UI and clicks "Add Selected". The app registers them as physical signals automatically.

4. The generated code will use the selected alias:
   ```python
   signal = query.channel(channel_alias_name="<selected_alias>")
   ```

**Available columns in the aliases table:**

| Column | Description |
|---|---|
| `channel_alias_name` | Alias name (e.g. `EngineSpeed`) — **default lookup column** |
| `channel_name` | Physical channel name (e.g. `Eng_Spd`) |
| `device_name` | Device/ECU name (e.g. `CAN1`) |

**Tips:**
- If the initial search returns too many results, narrow with additional terms.
- If no results are found, try a broader keyword or search on `channel_name` instead.
- One `channel_alias_name` may map to multiple `device_name` entries — the alias layer resolves this automatically at query time.

### 4. Add virtual signals

Virtual signals are created by applying operations to existing signals. Use `add_virtual_signal` with:
- `var_name`: a Python-safe variable name
- `expression`: a Python expression referencing existing signal `var_name` values
- `eval_type`: the resulting data type (`SampleSeries`, `Intervals`, `PointsInTime`, or `PitSeries`)

The main operation categories are:

#### Arithmetic (`+`, `-`, `*`, `/`)
```python
mean_temp = (temp_1 + temp_2) / 2
speed_kmh = speed_ms * 3.6
```

#### Comparisons → Intervals (`>`, `>=`, `<`, `<=`, `==`, `!=`)
```python
high_speed = speed > 100          # → Intervals
is_running = engine_speed > 0     # → Intervals
```

#### Logical combination of Intervals (`&`, `|`)
```python
fast_and_braking = (speed > 80) & (brake > 50)
```

#### Filtering with `.where()`
```python
# SampleSeries filtered by Intervals → SampleSeries
speed_while_braking = speed.where(brake > 50)

# SampleSeries filtered by PointsInTime → PitSeries
temp_at_events = temperature.where(engine_stop_events)
```

#### Event detection
```python
rising = signal.rising_edges()        # → PointsInTime
falling = signal.falling_edges()      # → PointsInTime
transitions = signal.change_points(from_state=0, to_state=1)  # → PointsInTime
```

#### Interval creation from events
```python
# flipflop: open interval at set_points, close at reset_points
intervals = set_points.flipflop(reset_points)  # → Intervals
# expand points into intervals
intervals = points.expand(width=5.0)            # → Intervals
```

#### Aggregation within intervals
```python
max_per_interval = signal.max_within_intervals(intervals)   # → SampleSeries
min_per_interval = signal.min_within_intervals(intervals)   # → SampleSeries
mean_per_interval = signal.mean_within_intervals(intervals) # → SampleSeries
```

#### Resampling and calculus
```python
resampled = signal.resample(sample_rate=0.1)  # 10 Hz
distance = speed.resample(1e8).cumtrapz()     # cumulative integral
acceleration = speed.resample(0.01).diff()    # discrete difference
```

#### Other transforms
```python
abs_signal = signal.abs()
exp_signal = signal.exp()
```

## Reference Documentation

Detailed API documentation for each data model class is available in the `references/` folder:

- [references/sample_series_api.md](references/sample_series_api.md) — SampleSeries methods (filtering, aggregation, histograms, calculus, resampling)
- [references/intervals_api.md](references/intervals_api.md) — Intervals methods (expand, shrink, filter, merge, delay)
- [references/points_in_time_api.md](references/points_in_time_api.md) — PointsInTime methods (expand, filter, flipflop, delay)
- [references/pit_series_api.md](references/pit_series_api.md) — PitSeries methods (histogram, min, max, synchronized)

## Edge Cases

- If the user doesn't know available signal/channel names, use the **Channel Alias Lookup** (step 3a) to search by keyword in the aliases table.
- If a virtual signal expression references a `var_name` that doesn't appear in the "Currently Defined Signals" list, warn the user that the signal must be added first.
- If the user wants to define signals that require operations not listed here, consult the full API docs in the references.
