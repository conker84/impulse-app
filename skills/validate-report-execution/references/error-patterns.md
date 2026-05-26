# Error Patterns Reference

Common errors when running Impulse framework reports, how to identify them, and how to fix them.

## Signal / Alias Errors

### Channel alias not found

**Pattern:**
```
Signal alias 'EngineSpeed' not found
```
or
```
No channel alias matching ... was found
```

**Cause:** The alias name in `01_signal_definitions.py` does not exist in the aliases table.

**Fix:**
1. Query the aliases table to find the correct name:
   ```sql
   SELECT DISTINCT channel_alias_name
   FROM <aliases_table>
   WHERE channel_alias_name LIKE '%<keyword>%'
   ORDER BY channel_alias_name
   LIMIT 20
   ```
2. Update the `query.channel(...)` call with the correct tag value.

### Signal not available for session

**Pattern:**
```
Signal ... not available in session ...
```

**Cause:** The alias exists but no physical channel matches for this specific vehicle/session. The vehicle may not have the sensor.

**Fix:** Check which signals are actually available for the vehicle:
```sql
SELECT DISTINCT signal_name
FROM <channel_metrics_table>
WHERE global_session_id IN (SELECT global_session_id FROM <container_metrics_table> WHERE test_object_id = '<vehicle_id>')
LIMIT 100
```

## Expression Type Errors

### Wrong type for histogram

**Pattern:**
```
TypeError: Cannot apply Histogram to Intervals
```
or
```
Expected SampleSeries but got Intervals
```

**Cause:** The `base_expr` evaluates to the wrong type. Common when a boolean condition (producing `Intervals`) is passed to a `Histogram` that expects `SampleSeries`.

**Fix:**
- `Histogram` with `agg_type="duration"` / `"distance"` / `"event_count"`: `base_expr` must be `SampleSeries` (a numeric signal, possibly filtered with `.where()`)
- `Histogram` with `agg_type="duration_count"`: `base_expr` must be `Intervals` (a boolean condition)

### Operation not supported between types

**Pattern:**
```
TypeError: unsupported operand type(s) for -: 'SampleSeries' and 'NoneType'
```

**Cause:** One of the signals in an arithmetic expression evaluated to `None` (channel not found, `.where()` produced empty result).

**Fix:** Check that all constituent signals resolve to valid data. Add defensive checks or verify the alias lookup.

## Config Errors

### Missing or malformed config fields

**Pattern:**
```
KeyError: 'container_metrics'
```
or
```
json.decoder.JSONDecodeError
```

**Cause:** Required field missing from `dev_config.json`, or JSON syntax error.

**Fix:** Read `dev_config.json`, verify all required fields are present and the JSON is valid. Compare against the template from `/configure-report`.

### Table or view not found

**Pattern:**
```
[TABLE_OR_VIEW_NOT_FOUND] The table or view ... cannot be found
```

**Cause:** A table path in `dev_config.json` is wrong — typo in catalog, schema, or table name.

**Fix:** Verify the table exists:
```sql
SHOW TABLES IN <catalog>.<schema> LIKE '<table_name>'
```
Correct the path in `dev_config.json`.

### Vehicle not found / no sessions

**Pattern:**
No error — job succeeds but produces no output. Or:
```
No sessions found for vehicle configuration
```

**Cause:** The `vehicle_id.value` in config doesn't match any records in `container_metrics`, or the `start_ts` is after all available data.

**Fix:**
```sql
SELECT test_object_id, MIN(measurement_first_datapoint_timestamp) as earliest, MAX(measurement_last_datapoint_timestamp) as latest, COUNT(*) as session_count
FROM <container_metrics_table>
WHERE test_object_id = '<vehicle_id>'
GROUP BY test_object_id
```
Verify the vehicle ID exists and the time range overlaps with available data.

## Permission Errors

### Access denied on source tables

**Pattern:**
```
[PERMISSION_DENIED] User does not have permission to access table ...
```

**Cause:** The cluster identity (user or service principal) lacks grants on source data tables.

**Fix:** This requires a workspace admin to grant access. Report the specific table and required permission (`SELECT`) to the user.

### Access denied on destination

**Pattern:**
```
[PERMISSION_DENIED] User does not have CREATE TABLE permission on schema ...
```

**Cause:** Cannot write to the destination schema.

**Fix:** Verify the destination catalog/schema exists and the user has write access. For dev, the schema `<destination_schema>` should already be accessible.

## Cluster / Infrastructure Errors

### Cloud provider launch error

**Pattern:**
```
CLOUD_PROVIDER_LAUNCH_ERROR: A]n error occurred while launching the cluster
```

**Cause:** Transient cloud infrastructure issue or invalid cluster configuration.

**Fix:** Retry the run. If persistent, check:
- `node_type_id` in `resources/jobs.yml` is valid
- Quota limits are not exceeded
- The cluster policy (if set) permits the configuration

### Driver unreachable

**Pattern:**
```
DRIVER_UNREACHABLE
```

**Cause:** The Spark driver crashed — usually out-of-memory or a fatal error during startup.

**Fix:**
- Check if `00_setup.py` has dependency conflicts
- Check the framework pin in `report_template/template/resources/jobs.yml.tmpl` (`@<commit-sha>`) resolves on github.com/databrickslabs/impulse
- Try a larger node type or reduce `max_batch_size` in config

## Impulse framework Errors

### Framework version not found

**Pattern:**
```
ERROR: Could not find a version that satisfies the requirement databricks-impulse @ git+https://github.com/databrickslabs/impulse@...
```

**Cause:** The commit SHA or tag in `report_template/template/resources/jobs.yml.tmpl` doesn't exist on `github.com/databrickslabs/impulse`.

**Fix:** Confirm the pin against the upstream repo and update if needed:
```bash
# Resolve the pin to a real commit; empty output = the ref doesn't exist
git ls-remote https://github.com/databrickslabs/impulse <ref>
```
Then edit the `@<commit-sha>` suffix in `report_template/template/resources/jobs.yml.tmpl` and re-deploy the affected report bundle.

### Solver errors

**Pattern:**
```
SolverError: ...
```
or
```
ValueError: config 'DEFAULT_V10' not recognized
```

**Cause:** Wrong `query_solver.config` value in `dev_config.json`.

**Fix:** Valid values are `"default"`, `"DEFAULT_V10"`, `"DEFAULT_V05"`, `"DEFAULT_V06"`. Use `"default"` for most cases.

## Histogram-Specific Errors

### Duplicate histogram name

**Pattern:**
```
ValueError: Histogram with name '...' already exists
```

**Cause:** Two histograms on the same page share the same `name` parameter.

**Fix:** Ensure every histogram has a unique `name` across the entire report.

### Empty bins list

**Pattern:**
```
ValueError: bins must have at least 2 elements
```

**Cause:** The `bins` parameter is empty or has only one edge.

**Fix:** Verify `range()` or `np.arange()` produces at least 2 values. Check min/max/width parameters.
