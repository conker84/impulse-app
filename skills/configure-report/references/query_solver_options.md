# Query Solver Configuration Reference

## Overview

The query solver is the engine that processes signal data for visualizations. It translates visualization definitions into SQL queries and executes them against the time-series data.

## Parameters

### `name` (required)
The type of solver to use.

| Value | Description |
|---|---|
| `"narrow_solver"` | Default solver for data in the narrow standard schema |
| `"delta_solver"` | Alternative solver for Delta-based data |

### `rle_data` (required)
Whether the source data is run-length encoded (RLE). RLE is a compression format where consecutive identical values are stored as a single entry with a count.

```json
"rle_data": "true"
```

Note: This is a string value (`"true"` / `"false"`), not a boolean.

### `config` (required)
Solver configuration version or path to a custom config file.

| Value | Description |
|---|---|
| `"DEFAULT_V10"` | Recommended default configuration |
| `"DEFAULT_V05"` | Default for narrow schema version 0.5 |
| `"DEFAULT_V06"` | Default for narrow schema version >= 0.6 and < 1.0 |
| `"<path>"` | Path to a custom solver configuration file |

### `max_batch_size` (optional)
Maximum number of visualizations processed by the query engine in a single batch. Controls memory usage for large reports with many visualizations.

- **Default**: `100000`
- **Typical value**: `10000`

```json
"max_batch_size": 10000
```

### `max_sessions_per_run` (optional)
Maximum number of measurement sessions processed per orchestrator run. Controls how much data is processed in a single execution of the batch orchestrator (`03_orchestrator.ipynb`).

- **Typical dev value**: `3` (for quick testing)
- **Typical prod value**: `10000` – `25000`

```json
"max_sessions_per_run": 25000
```

### `cache_solver_results` (optional)
Whether to cache query solver results in memory. Caching improves performance for repeated queries but increases memory usage.

- **Default**: `"true"`
- Set to `"false"` for large datasets to reduce memory pressure

```json
"cache_solver_results": "false"
```

Note: This is a string value (`"true"` / `"false"`), not a boolean.

## Common Configurations

### Development (fast iteration)
Small batch sizes for quick testing with minimal data.

```json
"query_solver": {
  "name": "narrow_solver",
  "rle_data": "true",
  "config": "DEFAULT_V10",
  "cache_solver_results": "false",
  "max_sessions_per_run": 3,
  "max_batch_size": 10000
}
```

### Production (large-scale processing)
Large session batches with caching disabled to manage memory.

```json
"query_solver": {
  "name": "narrow_solver",
  "rle_data": "true",
  "config": "DEFAULT_V10",
  "cache_solver_results": "false",
  "max_sessions_per_run": 25000,
  "max_batch_size": 10000
}
```
