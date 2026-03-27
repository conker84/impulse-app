# Data Source Configuration Reference

## Required Parameters

### `container_metrics`
Fully qualified path to the container/session metrics table. This table contains metadata about measurement sessions (timestamps, odometer, duration, etc.).

```json
"container_metrics": "catalog.schema.t_measurement_session_metric"
```

### `channel_metrics`
Fully qualified path to the channel/signal metrics table. This table contains metadata about available signals (signal names, units, data types).

```json
"channel_metrics": "catalog.schema.t_signal_metric"
```

### `channels`
Path to the signal data table(s) containing the actual time-series measurement data. Can be a single string or an array of strings when data is split across multiple tables.

```json
// Single table
"channels": "catalog.schema.measurement_signal_data_liquid_clustered"

// Multiple tables
"channels": ["catalog.schema.channels_table_A", "catalog.schema.channels_table_B"]
```

## Optional Parameters

### `aliases`
Path to channel aliases table. Enables use of alias-based channel lookup via `query.channel()` for resolving physical signal names from human-readable aliases.

```json
"aliases": "catalog.schema.vw_get_channelalias_denormalized_yarp"
```

### `aliases_copy_table_name`
Name for a local copy of the aliases table. **Required** if the aliases table is query-federated (e.g. from AzureSQL Server), because query-federated tables cannot be accessed directly on dedicated access mode clusters.

```json
"aliases_copy_table_name": "channel_aliases"
```

### `device_aliases`
Path to device aliases table. Enables use of `channel_with_device_alias()` in the QueryBuilder to extract signals via specific signal names and device aliases.

```json
"device_aliases": "catalog.schema.vw_get_device_alias_yarp"
```

### `device_aliases_copy_table_name`
Name for a local copy of the device aliases table. Created during preprocessing. Useful for working with a static copy when the original table is frequently updated.

```json
"device_aliases_copy_table_name": "device_aliases"
```

### `test_object_names`
Test object names corresponding to the `channels` tables. Must be in the **same order** as the channels array. Enables explicit signal ID filtering for better query performance.

```json
"channels": ["catalog.schema.channels_table_A", "catalog.schema.channels_table_B"],
"test_object_names": ["1", "2"]
```

Only use this for direct 1:1 mapping between test object names and channel tables. If this mapping doesn't apply, omit it — the framework will use an implicit filter via channel metrics joins.

### `global_report_table`
Path to a global report table storing report metadata and vehicle configuration. When provided together with `channel_mapping`, vehicle config is read from this table instead of the `vehicles` section.

```json
"global_report_table": "catalog.schema.global_report_table"
```

### `channel_mapping`
Configuration for mapping vehicles from the global report table to channel data locations.

```json
"channel_mapping": {
  "table_path": "catalog.schema.channel_mapping_table",
  "test_object_col_name": "test_object_name",
  "channel_location_col_name": "datapoint_location"
}
```

The channel mapping table should contain:

| Column | Description |
|---|---|
| `test_object_name` | Vehicle identifier matching the vehicle configuration |
| `datapoint_location` | Path to the channel table containing data for this test object |

## Common Configurations

### Basic (dev) — with multiple channel tables and alias copies
```json
"source": {
  "container_metrics": "<container_metrics_table>",
  "channel_metrics": "<channel_metrics_table>",
  "channels": [
    "<channels_table>",
    "<channels_table>"
  ],
  "aliases": "<aliases_table>",
  "aliases_copy_table_name": "channel_aliases",
  "device_aliases": "<device_aliases_table>",
  "device_aliases_copy_table_name": "device_aliases"
}
```

### With global report table and channel mapping
```json
"source": {
  "container_metrics": "<container_metrics_table>",
  "channel_metrics": "<channel_metrics_table>",
  "channels": [
    "<channels_table>",
    "<channels_table>"
  ],
  "aliases": "<aliases_table>",
  "aliases_copy_table_name": "channel_aliases",
  "device_aliases": "<device_aliases_table>",
  "device_aliases_copy_table_name": "device_aliases",
  "global_report_table": "catalog.schema.global_report_table",
  "channel_mapping": {
    "table_path": "catalog.schema.channel_mapping_table",
    "test_object_col_name": "test_object_name",
    "channel_location_col_name": "datapoint_location"
  }
}
```
