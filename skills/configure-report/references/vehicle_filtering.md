# Vehicle Filtering Reference

## Overview

The `vehicles` section in the config JSON defines which vehicles and time ranges to include in the report. At least one vehicle must be configured — the report will not work without vehicle filters.

## Vehicle Entry Structure

Each vehicle entry is an object with required and optional fields:

```json
{
  "vehicle_id": {
    "col_name": "test_object_name",
    "col_type": "string",
    "value": "167-5230"
  },
  "start_ts": {
    "col_name": "measurement_first_datapoint_timestamp",
    "col_type": "timestamp",
    "value": "2024-04-01 00:00:00"
  },
  "stop_ts": {
    "col_name": "measurement_last_datapoint_timestamp",
    "col_type": "timestamp",
    "value": "2025-01-31 00:00:00"
  },
  "max_duration_seconds": {
    "col_name": "measurement_duration_second",
    "value": 3600
  }
}
```

## Required Fields

### `vehicle_id`
Identifies which vehicle to filter for.

| Property | Description | Example |
|---|---|---|
| `col_name` | Column name in the session metrics table | `"test_object_id"` |
| `col_type` | Data type of the column | `"string"` |
| `value` | Vehicle ID value to match | `"167-5230"` |

### `start_ts`
Defines the start of the time range. Only sessions starting from this timestamp onward are included.

| Property | Description | Example |
|---|---|---|
| `col_name` | Column name for the start timestamp | `"measurement_first_datapoint_timestamp"` |
| `col_type` | Data type | `"timestamp"` |
| `value` | Start date in `YYYY-MM-DD HH:MM:SS` format | `"2024-04-01 00:00:00"` |

## Optional Fields

### `stop_ts`
Defines the end of the time range. If omitted, the report processes all data from `start_ts` onward (open-ended).

| Property | Description | Example |
|---|---|---|
| `col_name` | Column name for the stop timestamp | `"measurement_last_datapoint_timestamp"` |
| `col_type` | Data type | `"timestamp"` |
| `value` | End date in `YYYY-MM-DD HH:MM:SS` format | `"2025-01-31 00:00:00"` |

### `max_duration_seconds`
Restricts sessions by maximum duration. Only sessions whose duration column is less than or equal to this value are included. If omitted, the framework defaults to 3 days (259200 seconds).

| Property | Description | Example |
|---|---|---|
| `col_name` | Column name for the duration field | `"measurement_duration_second"` |
| `value` | Maximum duration in seconds (numeric, not string) | `3600` |

## Filter Logic

The framework builds a combined filter expression using OR between vehicles and AND within each vehicle:

```
(test_object_name == "167-5230" AND start_ts >= "2024-04-01 00:00:00" AND stop_ts <= "2025-01-31 00:00:00")
OR
(test_object_name == "214-862" AND start_ts >= "1980-01-01 00:00:00")
```

## Examples

### Single vehicle, bounded time range
```json
"vehicles": [
  {
    "vehicle_id": {"col_name": "test_object_name", "col_type": "string", "value": "167-5230"},
    "start_ts": {"col_name": "measurement_first_datapoint_timestamp", "col_type": "timestamp", "value": "2024-04-01 00:00:00"},
    "stop_ts": {"col_name": "measurement_last_datapoint_timestamp", "col_type": "timestamp", "value": "2025-01-31 00:00:00"}
  }
]
```

### Single vehicle, open-ended with max duration
```json
"vehicles": [
  {
    "vehicle_id": {"col_name": "test_object_name", "col_type": "string", "value": "174-605"},
    "start_ts": {"col_name": "measurement_first_datapoint_timestamp", "col_type": "timestamp", "value": "1970-01-01 00:00:00"},
    "max_duration_seconds": {"col_name": "measurement_duration_second", "value": 3600}
  }
]
```

### Multiple vehicles
```json
"vehicles": [
  {
    "vehicle_id": {"col_name": "test_object_name", "col_type": "string", "value": "167-5230"},
    "start_ts": {"col_name": "measurement_first_datapoint_timestamp", "col_type": "timestamp", "value": "2024-04-01 00:00:00"},
    "stop_ts": {"col_name": "measurement_last_datapoint_timestamp", "col_type": "timestamp", "value": "2025-01-31 00:00:00"},
    "max_duration_seconds": {"col_name": "measurement_duration_second", "value": 3600}
  },
  {
    "vehicle_id": {"col_name": "test_object_name", "col_type": "string", "value": "214-862"},
    "start_ts": {"col_name": "measurement_first_datapoint_timestamp", "col_type": "timestamp", "value": "1980-01-01 00:00:00"}
  }
]
```

## Common Column Names

These column names are used consistently across all existing reports:

| Purpose | Column name |
|---|---|
| Vehicle ID | `test_object_name` |
| Start timestamp | `measurement_first_datapoint_timestamp` |
| Stop timestamp | `measurement_last_datapoint_timestamp` |
| Session duration | `measurement_duration_second` |
