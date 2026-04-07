---
name: define-aggregations
description: Define aggregations (1D/2D histograms, statistics) and visualize results from gold layer tables. Use when the user wants to create aggregations during the wizard or query deployed report results.
compatibility: Part of the Impulse app. Used during the Aggregations wizard step and for post-deployment result analysis.
metadata:
  author: BDC-usecases
  version: "1.0"
allowed-tools: add_histogram add_histogram_2d add_statistics remove_aggregation preview_code mcp_execute_sql load_skill
---

# Define Aggregations

Help the user define aggregations on signals and visualize results from deployed reports. This skill covers the **Aggregations** wizard step and post-deployment gold layer querying.

## Aggregation Types

Three aggregation types are available. Choose based on what the user wants to analyze:

### 1D Histogram (`add_histogram`)

Distributes a signal's values into bins, weighted by time, distance, or event count.

**Four sub-types:**

| Type | What it measures | Input type | Use case |
|---|---|---|---|
| `duration` | Time spent in each bin | SampleSeries | Engine speed distribution, temperature profile |
| `distance` | Distance traveled in each bin | SampleSeries | Speed vs. distance driven |
| `duration_count` | How many intervals fall into each duration bin | Intervals | Cold start duration distribution |

**Tool call:**
```
add_histogram(
    name: str,              # Unique ID, convention: <short_name>_p<page>
    histogram_type: str,    # "duration" | "distance" | "duration_count"
    signal_ref: str,        # var_name of the signal to histogram
    bins: list[float],      # Bin edge values
    bins_unit: str,         # Unit for the x-axis (e.g. "rpm", "°C")
    description: str,       # Human-readable description
    event_ref: str,         # (optional) name of an interval event defined in Channels tab
    weight_signal_ref: str, # (distance only) var_name of the cumulative distance signal
    max_duration: float     # (duration only) max sample duration cap in nanoseconds
)
```

**Bin selection guidance:**
- Use physically meaningful ranges (engine speed: 0-7000 rpm, temperature: -40 to 160°C)
- Typically 10-20 bins is appropriate
- Use catch-all boundaries (-9999.0 / 9999.0) only when signal can have extreme outliers
- Call the LLM's `suggest-bins` endpoint or use domain knowledge from `define-channels` skill

### 2D Histogram (`add_histogram_2d`)

Heatmap showing correlation between two signals. Each cell accumulates duration where both signals simultaneously fall into their respective bins.

**Tool call:**
```
add_histogram_2d(
    name: str,              # Unique ID
    x_signal_ref: str,      # var_name for x-axis signal
    y_signal_ref: str,      # var_name for y-axis signal
    x_bins: list[float],    # Bin edges for x-axis
    y_bins: list[float],    # Bin edges for y-axis
    x_bins_unit: str,       # Unit for x-axis
    y_bins_unit: str,       # Unit for y-axis
    event_ref: str,         # (optional) name of an interval event defined in Channels tab
    description: str        # Human-readable description
)
```

**When to use:**
- Operating point maps (engine speed vs. torque)
- Correlation analysis (lateral acceleration vs. vehicle speed)
- Any time the user wants to see how two signals relate

**Common 2D histograms:**
- Engine speed vs. torque → powertrain operating map
- Vehicle speed vs. lateral acceleration → driving dynamics profile
- SOC vs. battery power → EV usage pattern
- Exhaust temp vs. RPM → thermal loading map

### Statistics (`add_statistics`)

Computes summary statistics (min, max, mean, median, std, count) across one or more signals.

**Tool call:**
```
add_statistics(
    name: str,              # Unique ID
    signal_refs: list[str], # var_names of signals to analyze
    stat_labels: list[str], # Which stats: ["min", "max", "mean", "median", "std", "count"]
    event_ref: str,         # (optional) name of an interval event defined in Channels tab
    description: str        # Human-readable description
)
```

**When to use:**
- Quick overview of signal ranges and distributions
- Comparing multiple signals side-by-side
- When histograms would be too detailed

## Decision Tree

```
User wants to analyze a signal
├── "How is the signal distributed?" → 1D Histogram (duration)
├── "How far do we drive at each value?" → 1D Histogram (distance)
├── "How long do operating conditions last?" → 1D Histogram (duration_count)
├── "How do two signals correlate?" → 2D Histogram
├── "What are the min/max/mean?" → Statistics
└── "Give me an overview" → Statistics + key histograms
```

## Signal Type Compatibility

| Aggregation | Required signal type |
|---|---|
| duration histogram | SampleSeries |
| distance histogram | SampleSeries |
| duration_count histogram | Intervals |
| 2D histogram | SampleSeries (both axes) |
| statistics | Any type |

## Post-Deployment: Querying Gold Layer Results

After a report is deployed and run, results are stored in Unity Catalog. See the `gold_layer_queries` reference for:
- Star schema structure (fact + dimension tables)
- SQL query patterns for all aggregation types
- Filtering by vehicle, time range, or mileage
- Cross-vehicle comparison queries

## References

- `histogram_1d_types.md` — Detailed 1D histogram constructor parameters and examples
- `histogram_2d_types.md` — 2D histogram definition and use cases
- `statistics_types.md` — Statistics aggregation details
- `gold_layer_queries.md` — SQL patterns for querying deployed results
