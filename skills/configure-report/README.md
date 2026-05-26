# Configure Report

Interactively configure the JSON config files for an Impulse framework report.

## Overview

This skill walks the user through configuring the report's JSON config file section by section. It reads the current config, identifies placeholder values that need replacing, and collects the correct values from the user. It covers all config sections: metadata, data sources, data destination, query solver, vehicles, and session metric table.

## What's Included

```
configure-report/
├── SKILL.md       # Configuration workflow, parameter reference tables, and guidance
└── references/    # Reserved for additional documentation
```

## Key Topics

- Report config JSON structure and all available parameters
- Data source table paths (container metrics, channel metrics, channels, aliases)
- Data destination setup (catalog, schema, table prefix, access groups)
- Query solver configuration (narrow solver, batch sizes, caching)
- Vehicle filter setup (vehicle IDs, date ranges, max duration)
- Session metric table configuration (columns, incremental processing, mappings)
- Placeholder detection and replacement

## When to Use

- After scaffolding a new report with `/create-report` to fill in real values
- When updating an existing report's configuration (e.g. adding vehicles, changing data sources)
- When promoting a report from dev to stg/prd and adjusting environment-specific settings
- User invokes `/configure-report` with optional report name and environment

## Related Skills

- [create-report](../create-report/) — scaffold a new report (run this first)
- [databricks-config](../databricks-config/) — configure Databricks CLI profile for deployment

## Resources

For detailed parameter documentation, refer to the Impulse framework docs (available locally):

- `<impulse_framework_path>/impulse_reporting/docs/getting_started.md` — overview and basic workflow
- `<impulse_framework_path>/impulse_reporting/docs/report/report.md` — full config parameter reference
- `<impulse_framework_path>/impulse_reporting/docs/filtering/filtering.md` — vehicle and channel filtering
- `<impulse_framework_path>/impulse_reporting/docs/persistence/persistence.md` — data persistence options
- `<impulse_framework_path>/impulse_reporting/docs/visualizations/` — visualization type documentation
