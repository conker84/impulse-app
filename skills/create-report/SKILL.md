---
name: create-report
description: Scaffold a new Impulse framework report in this repository. Use when the user wants to create, initialize, or add a new report to the project.
compatibility: Requires databricks CLI with a configured profile, and make.
allowed-tools: Bash Read
---

# Create Report

Scaffold a new Impulse framework report using the Databricks bundle template.

## Prerequisites

- The Databricks CLI must be installed.
- A Databricks CLI profile must be configured. Check `~/.databrickscfg` for available profiles. If no profile exists, ask the user to set one up first using the [databricks-config](../databricks-config/) skill (`/databricks-config`).
- The working directory must be the repository root containing the `Makefile` and `report_template/` directory.

## Steps

1. Check if a Databricks CLI profile is available in `~/.databrickscfg`.
   - If no profiles exist, stop and tell the user to configure one first via `/databricks-config`.
   - If exactly one profile exists, use it.
   - If multiple profiles exist, ask the user which profile to use.
2. Ask the user for the **report name**. It must be lowercase with underscores (e.g. `oil_pressure_report`). No spaces or hyphens.
3. Verify that a folder with that name does not already exist at the repository root.
4. Read the template schema from `report_template/databricks_template_schema.json` to get the current default values for all parameters.
5. **Always prompt the user** with an explicit choice before proceeding:
   - Ask: *"Do you want to use the default template values for this report, or configure the new report (dev/stg/prd hosts, groups)?"*
   - Do **not** assume defaults or skip this step. Wait for the user to answer.
   - **If the user chooses "use defaults"** (or equivalent): use all values from the template schema and proceed to step 6.
   - **If the user chooses "configure"** (or equivalent): present the template parameters and collect values as follows.
     The parameters (in order) are:
     - **dev_host**: Host URL of the DEV environment
     - **dev_group**: Group granted 'Manage' permissions for Databricks jobs in DEV
     - **stg_host**: Host URL of the STG environment (typically same as DEV)
     - **stg_group**: Group granted 'Manage' permissions for Databricks jobs in STG
     - **prd_host**: Host URL of the PRD environment
     - **prd_group**: Group granted 'Manage' permissions for Databricks jobs in PRD
     - **prd_sp_name**: App ID of the Service Principal in PRD
     Present the defaults in a summary table and let the user confirm or override each value (or accept all). Only prompt individually for parameters the user wants to change. The framework version is pinned in `report_template/template/resources/jobs.yml.tmpl` (not a per-report template parameter) — see the project README's "Impulse Framework" section.

6. Build a config JSON file containing all parameter values (report name + all collected values) and run:
   ```bash
   echo '<config_json>' > config_<report_name>.json && \
   databricks bundle init report_template --output-dir <report_name> --config-file config_<report_name>.json --profile <profile_name> && \
   rm config_<report_name>.json
   ```
   The config JSON must include all properties from the template schema, e.g.:
   ```json
   {
     "report_name": "my_report",
     "dev_host": "https://adb-...",
     "dev_group": "...",
     "stg_host": "https://adb-...",
     "stg_group": "...",
     "prd_host": "https://adb-...",
     "prd_group": "...",
     "prd_sp_name": "..."
   }
   ```
7. Confirm the new folder was created and show the user the generated structure.

## Generated Structure

After scaffolding, the new report folder contains:

```
<report_name>/
├── databricks.yml                 # Bundle config (dev/stg/prd targets)
├── azure-pipelines.yaml           # CI/CD pipeline
├── pyproject.toml                 # Python project config
├── src/
│   ├── 00_setup.py                # Package installation and imports
│   ├── 01_signal_definitions.py   # Signal definitions (to be customized)
│   ├── 02_report.ipynb            # Main report notebook
│   ├── 03_orchestrator.ipynb      # Batch processing orchestrator
│   ├── config/                    # Environment configs (dev/stg/prd)
│   ├── utils/                     # Schemas and utility functions
│   ├── chapters/                  # Report chapters and pages
│   ├── preprocessing/             # Status table initialization
│   └── postprocessing/            # Success/failure handlers
├── resources/
│   └── jobs.yml                   # Databricks job definition
└── tests/                         # Integration tests
```

## Next Steps After Scaffolding

Tell the user about these typical next steps:

1. **Configure vehicles**: Edit `src/config/dev_config.json` to set test object IDs and date ranges.
2. **Define signals**: Customize `src/01_signal_definitions.py` with the signals needed for the report.
3. **Build chapters and pages**: Add visualization pages under `src/chapters/`.
4. **Deploy and run**: Use `make run REPORT_NAME=<report_name>` to deploy and execute on Databricks.
5. **Test**: Use `make test REPORT_NAME=<report_name>` to run integration tests.

## Edge Cases

- If the report name already exists as a folder, abort and inform the user.
- If `databricks` CLI is not installed or no profile is configured, stop and direct the user to set one up via `/databricks-config`.
- Never skip the "use defaults or configure?" prompt: always ask the user before applying any template values.
