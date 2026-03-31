# Gold Layer Query Patterns

After a report is deployed and run, results are stored in Unity Catalog using a star schema. This reference covers querying patterns for all aggregation types.

## Table Naming Convention

Tables follow the pattern: `{catalog}.{schema}.{table_prefix}_{table_name}`

| Table suffix | Description |
|---|---|
| `histogram_fact` | One row per session per bin per histogram. Contains raw `hist_value`. |
| `histogram_dimension` | One row per histogram definition. Contains metadata (name, type, bins, units). |
| `session_dimension` | One row per measurement session. Used for filtering by vehicle, time, mileage. |

## Key Columns

### histogram_fact

| Column | Type | Description |
|---|---|---|
| `visual_id` | int | FK to histogram_dimension |
| `global_session_id` | string | FK to session_dimension |
| `bin_ID` | int | Bin index (0-based), use for ordering |
| `hist_value` | double | Raw aggregated value for this bin and session |
| `lower_bound` | double | Lower bin edge |
| `upper_bound` | double | Upper bin edge |
| `bin_name` | string | Human-readable bin label (e.g. "0 - 500") |

### histogram_dimension

| Column | Type | Description |
|---|---|---|
| `visual_id` | int | Primary key |
| `name` | string | Histogram identifier (e.g. "eng_spd_hist_p1") |
| `type` | string | "duration", "distance", "duration_count", "event_count" |
| `description` | string | Human-readable description |
| `bins` | array[double] | Bin edge values |
| `bins_unit` | string | Unit of the bin axis |
| `values_unit` | string | Unit of the values axis |

### session_dimension

| Column | Type | Description |
|---|---|---|
| `global_session_id` | string | Primary key |
| `test_object_id` | string | Vehicle identifier |
| `first_datapoint_timestamp` | timestamp | Session start |
| `last_datapoint_timestamp` | timestamp | Session end |
| `measurement_session_start_odo_mileage` | double | Start odometer |
| `measurement_session_end_odo_mileage` | double | End odometer |

## Understanding hist_value Units

| Histogram type | hist_value unit | Conversion for display |
|---|---|---|
| duration | nanoseconds | Divide by 1e9 for seconds, 3.6e12 for hours |
| distance | distance unit (typically km) | No conversion needed |
| duration_count | count (weighted) | No conversion needed |
| event_count | count (weighted) | No conversion needed |

## Query Patterns

### Step 1: Discover Available Histograms

```sql
SELECT visual_id, name, type, description, bins_unit, values_unit
FROM {table_prefix}_histogram_dimension
ORDER BY page_number, visual_id
```

### Step 2: Aggregate Histogram Data

The fact table has one row per session per bin. To produce a single aggregated histogram, SUM hist_value per bin.

**Duration histogram (convert nanoseconds to seconds):**

```sql
WITH aggregated AS (
  SELECT
    f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name,
    SUM(f.hist_value) / 1e9 AS hist_value_seconds
  FROM {table_prefix}_histogram_fact f
  JOIN {table_prefix}_histogram_dimension d ON f.visual_id = d.visual_id
  WHERE d.name = '{histogram_name}'
  GROUP BY f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name
),
totals AS (
  SELECT *, SUM(hist_value_seconds) OVER () AS total_value
  FROM aggregated
)
SELECT
  bin_ID, bin_name, lower_bound, upper_bound,
  hist_value_seconds,
  (hist_value_seconds / NULLIF(total_value, 0)) * 100 AS relative_pct
FROM totals
ORDER BY bin_ID ASC
```

**Distance / count histograms (no unit conversion):**

```sql
WITH aggregated AS (
  SELECT
    f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name,
    SUM(f.hist_value) AS hist_value
  FROM {table_prefix}_histogram_fact f
  JOIN {table_prefix}_histogram_dimension d ON f.visual_id = d.visual_id
  WHERE d.name = '{histogram_name}'
  GROUP BY f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name
),
totals AS (
  SELECT *, SUM(hist_value) OVER () AS total_value
  FROM aggregated
)
SELECT
  bin_ID, bin_name, lower_bound, upper_bound,
  hist_value,
  (hist_value / NULLIF(total_value, 0)) * 100 AS relative_pct
FROM totals
ORDER BY bin_ID ASC
```

### Step 3: Filter by Vehicle / Time / Mileage

Join with session_dimension before aggregating:

```sql
-- Filter by vehicle
SELECT f.bin_ID, f.bin_name, SUM(f.hist_value) / 1e9 AS hist_value_seconds
FROM {table_prefix}_histogram_fact f
JOIN {table_prefix}_histogram_dimension d ON f.visual_id = d.visual_id
JOIN {table_prefix}_session_dimension s ON f.global_session_id = s.global_session_id
WHERE d.name = '{histogram_name}'
  AND s.test_object_id = '{vehicle_id}'
GROUP BY f.bin_ID, f.bin_name
ORDER BY f.bin_ID ASC

-- Filter by time range
WHERE d.name = '{histogram_name}'
  AND s.first_datapoint_timestamp >= '{start_timestamp}'
  AND s.last_datapoint_timestamp <= '{end_timestamp}'

-- Filter by mileage range
WHERE d.name = '{histogram_name}'
  AND s.measurement_session_start_odo_mileage >= {min_km}
  AND s.measurement_session_end_odo_mileage <= {max_km}
```

### Step 4: Compare Across Vehicles

Group by `test_object_id` to produce side-by-side histograms:

```sql
SELECT
  s.test_object_id,
  f.bin_ID, f.bin_name,
  SUM(f.hist_value) / 1e9 AS hist_value_seconds
FROM {table_prefix}_histogram_fact f
JOIN {table_prefix}_histogram_dimension d ON f.visual_id = d.visual_id
JOIN {table_prefix}_session_dimension s ON f.global_session_id = s.global_session_id
WHERE d.name = '{histogram_name}'
GROUP BY s.test_object_id, f.bin_ID, f.bin_name
ORDER BY s.test_object_id, f.bin_ID ASC
```

## Edge Cases

- If `hist_value` is all zeros, `relative_pct` produces NULL (guarded by `NULLIF`)
- The `bins` array has N edges producing N-1 bins. Fact table has `bin_ID` 0 through N-2
- Catch-all bins (-9999.0 to 9999.0) use `bin_name` for display-friendly labels
- Duration histograms may have `max_duration` set — no additional processing needed at query time
