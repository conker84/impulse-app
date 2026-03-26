# Session Metric Table Configuration Reference

## Overview

The `session_metric_table` section defines which columns from the source session metrics table are included in the report's gold-layer sessions table. It also controls incremental processing behavior and column transformations.

## Parameters

### `columns` (required)
Array of column names to include from the session metrics table in the report's sessions table.

```json
"columns": [
  "test_object_id",
  "measurement_first_datapoint_timestamp",
  "measurement_last_datapoint_timestamp",
  "measurement_session_start_odo_mileage",
  "measurement_session_end_odo_mileage",
  "measurement_session_key",
  "load_timestamp"
]
```

### `last_modified_ts_col_name` (optional)
Column used for incremental processing. Must also be present in the `columns` array. During report generation, this column determines which sessions have been **updated** since the last run.

For detecting **inserted** sessions, the framework compares available sessions (silver layer) with processed sessions (gold layer) from the previous run.

```json
"last_modified_ts_col_name": "load_timestamp"
```

### `clustering_columns` (optional)
Columns for clustering the sessions table. Improves query performance for large datasets. All specified columns must also be present in the `columns` array.

```json
"clustering_columns": ["test_object_id", "measurement_first_datapoint_timestamp"]
```

### `col_name_mappings` (optional)
Array of column rename and cast operations. Creates new columns with the specified names and types. The original columns remain unchanged.

```json
"col_name_mappings": [
  {
    "existing_col_name": "measurement_first_datapoint_timestamp",
    "new_col_name": "first_datapoint_timestamp",
    "casting_type": "timestamp"
  },
  {
    "existing_col_name": "measurement_last_datapoint_timestamp",
    "new_col_name": "last_datapoint_timestamp",
    "casting_type": "timestamp"
  }
]
```

Each mapping has:

| Property | Description |
|---|---|
| `existing_col_name` | Original column name in the source table |
| `new_col_name` | New column name to create |
| `casting_type` | Type to cast to (e.g. `"timestamp"`) |

## Common Configuration

This is the standard session metric table config used across reports:

```json
"session_metric_table": {
  "columns": [
    "test_object_name",
    "measurement_first_datapoint_timestamp",
    "measurement_last_datapoint_timestamp",
    "measurement_session_start_odo_mileage",
    "measurement_session_end_odo_mileage",
    "measurement_session_name",
    "modified_timestamp"
  ],
  "last_modified_ts_col_name": "modified_timestamp",
  "col_name_mappings": [
    {
      "existing_col_name": "measurement_first_datapoint_timestamp",
      "new_col_name": "first_datapoint_timestamp",
      "casting_type": "timestamp"
    },
    {
      "existing_col_name": "measurement_last_datapoint_timestamp",
      "new_col_name": "last_datapoint_timestamp",
      "casting_type": "timestamp"
    }
  ]
}
```
