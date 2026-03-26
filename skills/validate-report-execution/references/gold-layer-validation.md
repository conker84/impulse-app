# Gold Layer Validation Reference

SQL queries and logic for validating Impulse framework report output tables.

All queries use these placeholders:
- `<catalog>` — from `data.destination.catalog` in config
- `<schema>` — from `data.destination.schema` in config
- `<prefix>` — from `data.destination.table_prefix` in config

Execute queries against the Databricks SQL warehouse using the SQL Statements API:

```bash
HOST="<workspace_host>"
TOKEN="<token>"
WH_ID="<warehouse_id>"

curl -s -X POST "$HOST/api/2.0/sql/statements/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"warehouse_id\": \"$WH_ID\",
    \"statement\": \"<SQL>\",
    \"wait_timeout\": \"50s\"
  }"
```

Or if a SQL warehouse ID is not known, find one first:

```bash
databricks warehouses list --profile <profile> -o json
```

## Level 1: Table Existence

### Check if output tables were created

```sql
SHOW TABLES IN <catalog>.<schema> LIKE '<prefix>*'
```

**Expected tables:**

| Table | Purpose |
|---|---|
| `<prefix>_histogram_fact` | Computed histogram bin values per session |
| `<prefix>_histogram_dim` | Histogram metadata: names, bin edges, units |
| `<prefix>_sessions` | Processed session metadata (timestamps, mileage) |
| `<prefix>_status` | Processing status per session |

**If no tables exist:**
- The job may have succeeded at the orchestrator level but no vehicle/session matched the filter.
- Check the `vehicles` section in `dev_config.json`:
  ```sql
  SELECT test_object_id, COUNT(*) as sessions,
         MIN(measurement_first_datapoint_timestamp) as earliest,
         MAX(measurement_last_datapoint_timestamp) as latest
  FROM <container_metrics_table>
  WHERE test_object_id = '<vehicle_id>'
  GROUP BY test_object_id
  ```
- Ensure `start_ts.value` falls within the data range.

**If only `_status` exists but not `_histogram_fact`:**
- Sessions were found but the report orchestrator failed silently. Check the status table:
  ```sql
  SELECT * FROM <catalog>.<schema>.<prefix>_status ORDER BY processing_timestamp DESC LIMIT 10
  ```

## Level 2: Row Counts

### Check if tables contain data

```sql
SELECT '<prefix>_sessions' AS table_name, COUNT(*) AS row_count
FROM <catalog>.<schema>.<prefix>_sessions
UNION ALL
SELECT '<prefix>_histogram_fact', COUNT(*)
FROM <catalog>.<schema>.<prefix>_histogram_fact
UNION ALL
SELECT '<prefix>_histogram_dim', COUNT(*)
FROM <catalog>.<schema>.<prefix>_histogram_dim
```

**Interpretation:**

| sessions | histogram_dim | histogram_fact | Meaning |
|---|---|---|---|
| > 0 | > 0 | > 0 | Data was processed — proceed to Level 3 |
| > 0 | > 0 | 0 | Histograms defined but no values computed — signals may be missing |
| > 0 | 0 | 0 | Sessions found but no histograms registered — check page code |
| 0 | 0 | 0 | No sessions matched — check vehicle filter |

**If sessions > 0 but histogram_fact = 0:**
- The signals referenced in histograms may not exist in the data for this vehicle.
- Check signal availability for the processed sessions:
  ```sql
  SELECT DISTINCT m.signal_name
  FROM <channel_metrics_table> m
  JOIN <catalog>.<schema>.<prefix>_sessions s
      ON m.global_session_id = s.global_session_id
  ORDER BY m.signal_name
  LIMIT 50
  ```

## Level 3: Histogram Values

### Summary per histogram

```sql
SELECT
    d.histogram_name,
    d.bins_unit,
    d.values_unit,
    COUNT(DISTINCT f.global_session_id) AS session_count,
    COUNT(*) AS bin_count,
    SUM(f.histogram_value) AS total_value,
    MAX(f.histogram_value) AS max_value,
    MIN(CASE WHEN f.histogram_value > 0 THEN f.histogram_value END) AS min_nonzero_value
FROM <catalog>.<schema>.<prefix>_histogram_fact f
JOIN <catalog>.<schema>.<prefix>_histogram_dim d
    ON f.histogram_id = d.histogram_id
GROUP BY d.histogram_name, d.bins_unit, d.values_unit
ORDER BY d.histogram_name
```

**Interpretation per histogram:**

| Condition | Verdict | Suggested Action |
|---|---|---|
| `total_value > 0`, multiple bins with data | Healthy | Report success |
| `total_value > 0`, only 1–2 bins with data | Data concentrated | May be correct (narrow signal range) or bins are misconfigured |
| `total_value = 0` | No data for this histogram | Investigate signal/enable condition |
| `session_count` < expected | Partial processing | Some sessions may have failed — check `_status` table |

### Detailed bin distribution for a specific histogram

```sql
SELECT
    d.histogram_name,
    f.bin_index,
    f.histogram_value,
    f.global_session_id
FROM <catalog>.<schema>.<prefix>_histogram_fact f
JOIN <catalog>.<schema>.<prefix>_histogram_dim d
    ON f.histogram_id = d.histogram_id
WHERE d.histogram_name = '<histogram_name>'
    AND f.histogram_value > 0
ORDER BY f.bin_index
LIMIT 50
```

### Check which histograms have all-zero values

```sql
SELECT d.histogram_name
FROM <catalog>.<schema>.<prefix>_histogram_dim d
LEFT JOIN (
    SELECT histogram_id, SUM(histogram_value) AS total
    FROM <catalog>.<schema>.<prefix>_histogram_fact
    GROUP BY histogram_id
    HAVING SUM(histogram_value) > 0
) f ON d.histogram_id = f.histogram_id
WHERE f.histogram_id IS NULL
ORDER BY d.histogram_name
```

This returns histograms that were defined but have zero values across all bins and sessions.

### Investigate a zero-value histogram

If a specific histogram has all-zero values:

1. **Check the dimension table** for its definition:
   ```sql
   SELECT * FROM <catalog>.<schema>.<prefix>_histogram_dim
   WHERE histogram_name = '<histogram_name>'
   ```
   Verify `bin_edges`, `bins_unit` look correct.

2. **Check if the underlying signal has data** by looking at channel metrics for the session:
   ```sql
   SELECT m.signal_name, m.signal_data_point_count
   FROM <channel_metrics_table> m
   JOIN <catalog>.<schema>.<prefix>_sessions s
       ON m.global_session_id = s.global_session_id
   WHERE m.signal_name LIKE '%<signal_keyword>%'
   LIMIT 20
   ```

3. **Common root causes for zero values:**
   - The alias resolves to a channel that has no data points for this vehicle
   - The `.where()` masking condition filters out all data (enable condition too restrictive)
   - Bin range doesn't cover the actual signal range (e.g. signal is in Kelvin but bins are in Celsius)
   - `max_duration` is too small, clipping all samples

## Status Table

### Check processing status

```sql
SELECT
    global_session_id,
    status,
    error_message,
    processing_timestamp
FROM <catalog>.<schema>.<prefix>_status
ORDER BY processing_timestamp DESC
LIMIT 20
```

**Status values:**
- `SUCCESS` — session processed without errors
- `FAILED` — session processing failed; check `error_message`
- `PENDING` — session queued but not yet processed

If many sessions show `FAILED`, the `error_message` column often contains the specific signal or expression that caused the failure.
