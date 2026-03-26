# Create Report

Scaffold a new Impulse framework report in this repository using the Databricks bundle template.

## Overview

This skill walks through creating a new report folder from the `.template/` blueprint. It validates that a Databricks CLI profile is available, asks for a report name, runs the scaffolding command, and guides the user through next steps like configuring vehicles, defining signals, and building chapters.

## What's Included

```
create-report/
└── SKILL.md    # Scaffolding workflow, template parameters, generated structure, and next steps
```

## Key Topics

- Report scaffolding via `make init-template` / `databricks bundle init`
- Template parameter defaults and post-scaffolding customization
- Impulse framework report structure (chapters, pages, signals, configs)
- Databricks bundle deployment and job execution

## When to Use

- Creating a brand new Impulse framework report from scratch
- User invokes `/create-report` with or without a report name
- User asks to "add a new report", "initialize a report", or "scaffold a report"

## Related Skills

- [databricks-config](../databricks-config/) -- configure a Databricks CLI profile (required before creating a report if no profile exists)

## Resources

- [Databricks Asset Bundles](https://docs.databricks.com/dev-tools/bundles/index.html)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html)
