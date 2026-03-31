# Vehicle Discovery Reference

## Silver Layer Table Structure

Vehicle candidates are discovered from the `container_tags` or `container_metrics` tables in the silver layer. These tables contain one row per measurement session per vehicle.

### Key Columns

| Column | Description |
|---|---|
| `test_object_name` | Vehicle identifier (e.g. "167-5230") |
| `test_object_id` | Alternative vehicle ID format |
| `measurement_first_datapoint_timestamp` | Session start time |
| `measurement_last_datapoint_timestamp` | Session end time |
| `measurement_duration_second` | Session duration in seconds |
| `global_session_id` | Unique session identifier |

## Discovery Queries

### List all vehicles with data volume

```sql
SELECT
    test_object_name AS vehicle_id,
    COUNT(*) AS session_count,
    MIN(measurement_first_datapoint_timestamp) AS first_data,
    MAX(measurement_last_datapoint_timestamp) AS last_data,
    SUM(measurement_duration_second) / 3600.0 AS total_hours
FROM {catalog}.{schema}.container_metrics
GROUP BY test_object_name
ORDER BY session_count DESC
```

### Check data availability for a specific vehicle

```sql
SELECT
    test_object_name AS vehicle_id,
    COUNT(*) AS session_count,
    MIN(measurement_first_datapoint_timestamp) AS first_data,
    MAX(measurement_last_datapoint_timestamp) AS last_data,
    SUM(measurement_duration_second) / 3600.0 AS total_hours,
    AVG(measurement_duration_second) / 60.0 AS avg_session_minutes
FROM {catalog}.{schema}.container_metrics
WHERE test_object_name = '{vehicle_id}'
GROUP BY test_object_name
```

### List available channels for a vehicle

```sql
SELECT DISTINCT
    cm.channel_name,
    cm.unit,
    cm.sample_count,
    cm.min_value,
    cm.max_value
FROM {catalog}.{schema}.channel_metrics cm
JOIN {catalog}.{schema}.container_metrics ct
    ON cm.global_session_id = ct.global_session_id
WHERE ct.test_object_name = '{vehicle_id}'
ORDER BY cm.channel_name
```

## Vehicle Filter Configuration

Each vehicle in the report config has the following structure:

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
    }
}
```

- `vehicle_id` is required
- `start_ts` defaults to epoch (all data) if not specified
- `stop_ts` is optional (open-ended if omitted)

Multiple vehicles are combined with OR logic — sessions matching any vehicle filter are included.
