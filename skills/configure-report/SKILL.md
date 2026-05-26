---
name: configure-report
description: Configure an Impulse framework report by walking through the JSON config file sections (metadata, data sources, destination, query solver, vehicles, session metrics). Use when the user wants to set up, update, or review report configuration.
compatibility: Requires a scaffolded Impulse report folder in the repository.
allowed-tools: Bash Read Edit
---

# Configure Report

Interactively configure the JSON config files for an Impulse framework report.

**Usage:** `/configure-report [report_name] [environment]`

Examples:
- `/configure-report` — select report and environment interactively
- `/configure-report my_report` — configure my_report (ask which environment)
- `/configure-report my_report dev` — configure my_report's dev config directly

## Prerequisites

- The report folder must already exist (scaffolded via `/create-report` or manually).
- The Impulse framework documentation should be available locally. If you need to look up details about configuration parameters, ask the user for the path to the Impulse framework base folder. The relevant docs are at `<impulse_framework_path>/impulse_reporting/docs/`.

## Steps

### 1. Identify report and environment

- If no report name is provided, list the top-level folders in the repository and ask the user which report to configure.
- If no environment is provided, ask the user which config to edit: `dev`, `stg`, or `prd`.
- Read the target config file at `<report_name>/src/config/<env>_config.json`.

### 2. Configure vehicles FIRST

**Always start by asking the user which vehicles to include in the report.** This is the most important configuration step because the vehicle IDs determine which source tables need to be configured.

Collect for each vehicle:
- Vehicle ID (e.g. `VH-001`)
- Start timestamp (format: `YYYY-MM-DD HH:MM:SS`)
- Optionally: stop timestamp, max duration

### 3. Auto-resolve source tables from vehicle IDs

After the user provides vehicle IDs, **automatically look up all source tables** by querying the mapping table in Unity Catalog:

**Mapping table:** `<catalog>.<schema>.<vehicle_mapping_table>`

Query the mapping table for the given vehicle IDs to resolve all source table paths:

```sql
SELECT DISTINCT test_object_name, datapoint_location, measurement_session_metric, signal_metric_location
FROM <catalog>.<schema>.<vehicle_mapping_table>
WHERE test_object_name IN ('<vehicle_id_1>', '<vehicle_id_2>', ...)
```

From the results, extract:
- **`channels`** — from `datapoint_location`: the fully qualified channel table path per vehicle (e.g. `...t_100000151_signal_data_point`). Use the distinct values as the `channels` array.
- **`container_metrics`** — from `measurement_session_metric`: the fully qualified session metrics table path.
- **`channel_metrics`** — from `signal_metric_location`: the fully qualified signal metrics table path.

Present the complete vehicle-to-table mapping to the user for confirmation before applying:

> "Based on the vehicle IDs, I found the following source tables:
> - Vehicle `VH-001` → channels: `<signal_data_table_1>`
> - Vehicle `VH-002` → channels: `<signal_data_table_2>`
> - Container metrics: `<container_metrics_table>`
> - Channel metrics: `<channel_metrics_table>`
>
> I'll configure the data sources accordingly. Does this look correct?"

If a vehicle ID is not found in the mapping table, warn the user and ask them to provide the table paths manually.

### 4. Determine remaining configuration scope

After vehicles and data sources are resolved, ask the user if they want to configure additional sections:

- **Metadata** — report name, description, creator, source code URL
- **Data Destination** — target catalog, schema, table prefix, access groups
- **Query Solver** — solver type, RLE data, config version, batch sizes
- **Session Metric Table** — columns, incremental processing, column mappings

The remaining source fields (`aliases`, `device_aliases`) have well-known defaults — use these unless the user wants to override them:
- `aliases`: `<aliases_table>`
- `device_aliases`: `<device_aliases_table>`

### 5. Walk through selected sections

For each selected section, read the current values from the config file and walk through them with the user. Use the guidance below for each section.

#### Metadata

| Field | Description | Required |
|---|---|---|
| `report_name` | Display name for the report | Yes |
| `description` | Short description of the report | No |
| `report_creator` | Team or person who created the report | No |
| `source_code` | URL to the source code repository | No |

Show current values and ask if the user wants to change any.

#### Data Source

| Field | Description | Required |
|---|---|---|
| `container_metrics` | Fully qualified path to container/session metrics table | Yes |
| `channel_metrics` | Fully qualified path to channel/signal metrics table | Yes |
| `channels` | Path to signal data table(s). Can be a string or array of strings | Yes |
| `aliases` | Path to channel aliases table | No |
| `aliases_copy_table_name` | Name for local copy of aliases table (required if aliases is query-federated) | No |
| `device_aliases` | Path to device aliases table | No |
| `device_aliases_copy_table_name` | Name for local copy of device aliases table | No |
| `test_object_names` | Test object names matching the order of `channels` tables | No |
| `global_report_table` | Path to global report metadata table | No |
| `channel_mapping.table_path` | Path to channel mapping table | No |
| `channel_mapping.test_object_col_name` | Column name for test object name in mapping table | No |
| `channel_mapping.channel_location_col_name` | Column name for channel location in mapping table | No |

Important notes to communicate to the user:
- All table paths must be fully qualified: `catalog.schema.table_name`
- If `aliases` points to a query-federated table (e.g. AzureSQL), then `aliases_copy_table_name` is required
- `test_object_names` must match the order of `channels` tables (only for direct 1:1 mapping)
- If `global_report_table` and `channel_mapping` are both provided, vehicle config is read from the global report table instead of the `vehicles` section

#### Data Destination

| Field | Description | Required |
|---|---|---|
| `catalog` | Target Unity Catalog name | Yes |
| `schema` | Target schema name | Yes |
| `table_prefix` | Prefix for all generated tables | Yes |
| `clustering_columns` | Columns for liquid clustering on fact tables (e.g. `["global_session_id"]`) | No |
| `access_groups` | Array of `[group_name, privilege]` pairs for access control | No |
| `schema_managed_location` | Custom storage location for the schema (`abfss://...`) | No |

Note: For production configs, `access_groups` and `schema_managed_location` are typically required.

#### Query Solver

| Field | Description | Required | Default |
|---|---|---|---|
| `name` | Solver type | Yes | `"narrow_solver"` |
| `rle_data` | Whether data is run-length encoded | Yes | `"true"` |
| `config` | Solver config version | Yes | `"DEFAULT_V10"` |
| `max_sessions_per_run` | Max sessions processed per orchestrator run | No | — |
| `max_batch_size` | Max visualizations per solver batch | No | `100000` |
| `cache_solver_results` | Cache solver results in memory | No | `"true"` |

Notes to communicate:
- Valid config versions: `"DEFAULT_V10"` (recommended default), `"DEFAULT_V05"` (narrow schema v0.5), `"DEFAULT_V06"` (narrow schema >= v0.6)
- For large datasets, consider setting `cache_solver_results` to `"false"` to reduce memory usage
- `max_sessions_per_run` controls how many sessions the batch orchestrator processes per iteration

#### Vehicles

At least one vehicle must be configured. For each vehicle, collect:

| Field | Description | Required |
|---|---|---|
| `vehicle_id.col_name` | Column name for vehicle ID | Yes |
| `vehicle_id.col_type` | Data type (typically `"string"`) | Yes |
| `vehicle_id.value` | Vehicle ID to filter for | Yes |
| `start_ts.col_name` | Column name for start timestamp | Yes |
| `start_ts.col_type` | Data type (typically `"timestamp"`) | Yes |
| `start_ts.value` | Start date (format: `"YYYY-MM-DD HH:MM:SS"`) | Yes |
| `stop_ts.col_name` | Column name for stop timestamp | No |
| `stop_ts.col_type` | Data type | No |
| `stop_ts.value` | End date | No |
| `max_duration_seconds.col_name` | Column name for duration | No |
| `max_duration_seconds.value` | Max session duration in seconds | No |

Important notes:
- If `stop_ts` is omitted, the report processes all data from `start_ts` onward
- If `max_duration_seconds` is omitted, the framework defaults to 3 days (259200 seconds)
- The user should provide actual vehicle IDs — the template placeholder `<vehicle_id>` must be replaced
- Ask the user how many vehicles they want to configure and collect details for each

When collecting vehicle details, use the same column names as the existing config. Typically:
- `vehicle_id.col_name` = `"test_object_name"`
- `start_ts.col_name` = `"measurement_first_datapoint_timestamp"`
- `stop_ts.col_name` = `"measurement_last_datapoint_timestamp"`
- `max_duration_seconds.col_name` = `"measurement_duration_second"`

#### Session Metric Table

| Field | Description | Required |
|---|---|---|
| `columns` | Array of column names to include from session metrics | Yes |
| `last_modified_ts_col_name` | Column for incremental processing (must also be in `columns`) | No |
| `clustering_columns` | Columns for clustering the sessions table (must also be in `columns`) | No |
| `col_name_mappings` | Array of column rename/cast operations | No |

The template provides sensible defaults for this section. Only prompt the user to change it if they specifically selected this section.

### 6. Apply changes

After collecting all values, update the config JSON file using the Edit tool. Preserve the existing structure and only modify the sections the user chose to configure. Ensure valid JSON formatting.

### 7. Review

After saving, display a summary of the changes made and show the updated config file. If there are still placeholder values remaining (e.g. `<vehicle_id>`, `<channels_table>`), warn the user that these need to be replaced before the report can run.

## Reference Documentation

Detailed parameter documentation is available in the `references/` folder. Load these on demand when you need more detail for a specific section:

- [references/data_source_parameters.md](references/data_source_parameters.md) — all source config fields, common configurations, alias and channel mapping details
- [references/data_destination_parameters.md](references/data_destination_parameters.md) — destination config fields, access groups, dev vs prd examples
- [references/vehicle_filtering.md](references/vehicle_filtering.md) — vehicle filter structure, filter logic, examples for single/multiple vehicles
- [references/query_solver_options.md](references/query_solver_options.md) — solver types, config versions, batch sizing, dev vs prd tuning
- [references/session_metric_table.md](references/session_metric_table.md) — columns, incremental processing, column mappings

For additional detail beyond what the references cover, the Impulse framework documentation may be available locally. Ask the user for the path to the Impulse framework base folder. The relevant docs are at `<impulse_framework_path>/impulse_reporting/docs/`.

## Edge Cases

- If the config file doesn't exist, warn the user and suggest running `/create-report` first.
- If the config contains placeholder values from the template (e.g. `<container_metrics_table>`), highlight these and prompt the user to provide real values.
- If the user wants to configure multiple environments at once, process them sequentially and ask if values should be copied between environments.
- If the user is unsure about table paths or column names, suggest they check their Databricks workspace or ask a team member.
