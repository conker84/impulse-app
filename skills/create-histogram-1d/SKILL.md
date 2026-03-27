---
name: create-histogram-1d
description: Create 1D histogram visualizations for an Impulse framework report. Use when the user wants to add duration, distance, duration count, or event count histograms.
compatibility: Part of the Impulse app. Loaded on-demand during the Aggregations wizard step.
metadata:
  author: BDC-usecases
  version: "2.0"
allowed-tools: add_histogram load_skill
---

# Create 1D Histogram

Add 1D histogram visualizations to an Impulse framework report. This skill is loaded on-demand by the LLM agent during the **Aggregations** wizard step of the Impulse app.

## Context

- Signals must already be defined in the previous Channels step. The system prompt includes a **Currently Defined Signals** section listing all available signals with their `var_name` and `eval_type`.
- Histograms can be added via the `add_histogram` tool or the HistogramBuilder UI form in the right panel.
- The final histogram page code is auto-generated at deploy time — you do not edit files directly.

## Histogram Types

There are four types of 1D histograms. Choose the right one based on what the user wants to measure:

| Type | Class | What it measures | Input expression type |
|---|---|---|---|
| **Duration** | `Histogram(agg_type="duration")` | Time spent in each value bin | `SampleSeries` |
| **Distance** | `Histogram(agg_type="distance")` | Distance traveled in each value bin | `SampleSeries` |
| **Duration Count** | `Histogram(agg_type="duration_count")` | Number of events by their duration | `Intervals` |
| **Event Count** | `Histogram(agg_type="event_count")` | Number of events at signal values | `SampleSeries` + event `BasicEvent` |

## Steps

### 1. Check available signals

Review the "Currently Defined Signals" section in the system prompt. Each signal lists its `var_name` and `eval_type`. Use this to determine which signals are suitable for each histogram type.

### 2. Determine histogram type

Ask the user what they want to analyze. Map their intent to the correct type:

- "How long does the signal spend in each range?" → **duration**
- "How much distance is covered at each signal value?" → **distance**
- "How long do events/conditions last?" → **duration_count**
- "How often does an event occur at each signal value?" → **event_count**

### 3. Collect parameters

The `add_histogram` tool accepts the following parameters. For all types:

| Tool parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique identifier for the histogram. Convention: `<short_name>_p<page_number>` |
| `histogram_type` | str | Yes | One of: `duration`, `distance`, `duration_count`, `event_count` |
| `signal_ref` | str | Yes | The `var_name` of the signal to histogram (must exist in Currently Defined Signals) |
| `bins` | list[float] | Yes | Bin edge values. See bin definition patterns below. |
| `description` | str | No | Human-readable description |
| `bins_unit` | str | No | Unit label for the bins axis (e.g. `"rpm"`, `"°C"`, `"km/h"`) |

Additional parameters per type:

**duration:**

| Tool parameter | Type | Required | Description |
|---|---|---|---|
| `max_duration` | float | No | Maximum sample duration in nanoseconds. Caps individual samples to avoid outlier inflation. Common value: `100000000000` (100 seconds). |

**distance:**

Note: The distance histogram also requires a cumulative distance signal as a weight. Pass `weight_signal_ref` (the `var_name` of a cumulative distance `SampleSeries`) alongside the other parameters.

**duration_count:**

| Tool parameter | Type | Required | Description |
|---|---|---|---|
| `weight_const` | float | No | Constant weight per event. Typically `1.0`. |

**event_count:**

| Tool parameter | Type | Required | Description |
|---|---|---|---|
| `event_signal_ref` | str | Yes | `var_name` of the event trigger signal (must be a `PointsInTime`). |
| `weight_const` | float | No | Constant weight per event. Typically `1.0`. |

### 4. Define bins

Help the user define bin edges. Common patterns:

```python
# Equidistant bins
bins = [float(i) for i in range(0, 6000, 500)]        # 0, 500, 1000, ..., 5500

# With catch-all boundary bins
bins = [-9999.0] + [float(i) for i in range(150, 360, 10)] + [9999.0]

# Custom non-equidistant bins
bins = [0, 10, 25, 50, 100, 200, 500, 1000]
```

When passing bins via the `add_histogram` tool, provide the fully expanded list of floats (e.g. `[0, 500, 1000, 1500, ...]`).

Important notes about bins:
- Bin edges define the boundaries between bins. N edges create N-1 bins.
- Values below the first edge or above the last edge are not counted. Use `-9999.0` / `9999.0` as catch-all boundaries if needed.
- For `duration_count`, bins are in **nanoseconds** (duration of intervals).
- For `duration` and `event_count`, bins are in the unit of the `signal_ref` signal.

### 5. Add the histogram

Call the `add_histogram` tool with the collected parameters. Example for a duration histogram:

```json
{
  "name": "eng_spd_hist_p1",
  "histogram_type": "duration",
  "signal_ref": "Eng_Spd_masked",
  "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500],
  "bins_unit": "rpm",
  "max_duration": 100000000000,
  "description": "Distribution of engine speed over time"
}
```

Alternatively, the user may fill out the HistogramBuilder form in the right panel directly. The form handles the same parameters.

### 6. Verify expression types

Before calling `add_histogram`, verify the signal's `eval_type` (shown in the system prompt's signal list) matches what the histogram expects:

- **duration**: `signal_ref` must be a `SampleSeries`
- **distance**: `signal_ref` and `weight_signal_ref` must be `SampleSeries`
- **duration_count**: `signal_ref` must be `Intervals`
- **event_count**: `signal_ref` must be a `SampleSeries`, `event_signal_ref` must be `PointsInTime`

If the types do not match, inform the user and suggest defining a suitable signal first via the Channels step.

## Reference Documentation

- [references/histogram_types.md](references/histogram_types.md) — detailed constructor parameters, examples, and persistence schema

## Edge Cases

- If the user needs a signal that doesn't exist yet, suggest defining it first via the Channels step (`load_skill("define-channels")`).
- If the user wants catch-all bins (to capture outliers), add `-9999.0` and `9999.0` as boundary edges.
- If the histogram name already exists in the current report state, warn about duplicate names — each histogram must have a unique `name`.
- If `signal_ref` references a `var_name` that is not in the Currently Defined Signals list, inform the user and do not call `add_histogram`.
