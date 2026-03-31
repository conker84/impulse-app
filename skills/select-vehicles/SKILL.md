---
name: select-vehicles
description: Select test vehicles and configure data sources for an Impulse report. Use when the user needs help with vehicle selection, timestamp filtering, or data source configuration during the Vehicles wizard step.
compatibility: Part of the Impulse app. Loaded on-demand during the Vehicles wizard step.
metadata:
  author: BDC-usecases
  version: "1.0"
allowed-tools: set_vehicle set_data_sources mcp_execute_sql load_skill
---

# Select Vehicles

Help the user select test vehicles and configure data sources for an Impulse framework report. This skill is loaded on-demand by the LLM agent during the **Vehicles** wizard step.

## How Vehicle Selection Works

The Impulse app discovers available vehicles automatically from the silver layer data and presents them as checkboxes in the right panel. The user selects vehicles and clicks "Add Selected" — the UI handles the rest.

**Your role is typically minimal.** The UI handles:
- Discovering available vehicles from the silver layer `container_tags` table
- Presenting vehicle candidates as checkboxes
- Auto-configuring data sources when vehicles are added

**You intervene only when the user needs to:**
- Manually add a vehicle not in the candidate list
- Set start/stop timestamps for a specific vehicle
- Override the default data source configuration
- Query what vehicles or data are available

## Tools

### `set_vehicle`

Add or update a single vehicle configuration.

```
set_vehicle(
    vehicle_id: str,        # Vehicle identifier (e.g. "167-5230")
    col_name: str = "test_object_name",  # Column name in session metrics table
    start_ts: str | None,   # Start timestamp "YYYY-MM-DD HH:MM:SS" (optional)
    stop_ts: str | None     # Stop timestamp "YYYY-MM-DD HH:MM:SS" (optional)
)
```

**When to use:**
- User wants to filter a vehicle to a specific time range
- User wants to add a vehicle not shown in the UI candidates

**Example:** "Only include data from March 2024 onwards for vehicle 167-5230"
```
set_vehicle("167-5230", start_ts="2024-03-01 00:00:00")
```

### `set_data_sources`

Configure the mapping tables that connect vehicles to their measurement data.

```
set_data_sources(
    container_metrics: str,   # Container metrics table (fully qualified)
    channel_metrics: str,     # Channel metrics table
    channels: str,            # Channel aliases table
    aliases: str,             # Alias scope table
    device_aliases: str,      # Device alias mapping
    destination_catalog: str, # Output catalog for results
    destination_schema: str,  # Output schema for results
    table_prefix: str         # Prefix for output tables
)
```

**When to use:** Only when the user explicitly asks to override data source tables. The UI auto-configures these from the selected vehicles.

## Querying Available Vehicles

If the user asks what vehicles are available, you can query the silver layer directly:

```sql
SELECT DISTINCT test_object_name,
       COUNT(*) AS session_count,
       MIN(measurement_first_datapoint_timestamp) AS first_data,
       MAX(measurement_last_datapoint_timestamp) AS last_data
FROM {container_metrics_table}
GROUP BY test_object_name
ORDER BY session_count DESC
```

The `container_metrics_table` is auto-discovered from the app's data source configuration.

## Timestamp Filtering

Vehicles can be filtered by time range to focus on specific test periods:

- **start_ts** — Only include measurement sessions starting from this timestamp
- **stop_ts** — Only include sessions ending before this timestamp (optional, open-ended if omitted)

This is useful for:
- Excluding early test runs with incomplete setups
- Focusing on a specific test campaign
- Comparing data from different time periods

## Common Patterns

### "Show me what vehicles are available"
The UI already shows candidates. If the list is empty or the user wants more detail, query the container_metrics table via `mcp_execute_sql`.

### "Only use data from the last 3 months"
Use `set_vehicle` with a `start_ts` for each selected vehicle.

### "Add vehicle X manually"
Use `set_vehicle` with the vehicle ID. The data sources will be auto-configured.

### "What data exists for vehicle X?"
Query the channel_metrics table filtered by the vehicle ID to show available channels and data volume.
