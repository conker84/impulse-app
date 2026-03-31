# Vehicle Discovery Reference

## Silver Layer Table Structure

Vehicle candidates are discovered from the `container_tags` or `container_metrics` tables in the silver layer. These tables contain one row per measurement session per vehicle.

### Key Columns

Column names vary by data source. Common patterns:

| Purpose | Possible column names |
|---|---|
| Vehicle identifier | `vehicle_key`, `test_object_name`, `test_object_id` |
| Session start time | `measurement_first_datapoint_timestamp` |
| Session end time | `measurement_last_datapoint_timestamp` |
| Session duration | `measurement_duration_second` |
| Session identifier | `global_session_id` |

**IMPORTANT:** Always check the actual table schema before querying. Use `DESCRIBE TABLE` or check the configured data sources in the report state to find the correct column names.

## Discovery Queries

Before running these queries, verify column names with:
```sql
DESCRIBE TABLE {container_metrics_table}
```

### List all vehicles with data volume

```sql
-- Replace {vehicle_col} with the actual vehicle ID column name
SELECT
    {vehicle_col} AS vehicle_id,
    COUNT(*) AS session_count,
    MIN(measurement_first_datapoint_timestamp) AS first_data,
    MAX(measurement_last_datapoint_timestamp) AS last_data
FROM {container_metrics_table}
GROUP BY {vehicle_col}
ORDER BY session_count DESC
```

### Check data availability for a specific vehicle

```sql
SELECT
    {vehicle_col} AS vehicle_id,
    COUNT(*) AS session_count,
    MIN(measurement_first_datapoint_timestamp) AS first_data,
    MAX(measurement_last_datapoint_timestamp) AS last_data
FROM {container_metrics_table}
WHERE {vehicle_col} = '{vehicle_id}'
GROUP BY {vehicle_col}
```

### List available channels for a vehicle

```sql
SELECT DISTINCT
    cm.channel_name,
    cm.unit,
    cm.sample_count,
    cm.min_value,
    cm.max_value
FROM {channel_metrics_table} cm
JOIN {container_metrics_table} ct
    ON cm.global_session_id = ct.global_session_id
WHERE ct.{vehicle_col} = '{vehicle_id}'
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
