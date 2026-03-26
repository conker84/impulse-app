# Data Destination Configuration Reference

## Required Parameters

### `catalog`
Target Unity Catalog name where all report tables will be created.

```json
"catalog": "<destination_catalog>"
```

### `schema`
Target schema name within the catalog. All report tables are created here.

```json
"schema": "<destination_schema>"
```

### `table_prefix`
Prefix applied to all generated table names. Helps distinguish tables from different reports within the same schema.

```json
"table_prefix": "my_report"
```

Generated tables will be named like: `<table_prefix>_histogram_fact`, `<table_prefix>_histogram_dim`, `<table_prefix>_sessions`, etc.

## Optional Parameters

### `clustering_columns`
Columns to use for liquid clustering on fact tables (e.g. histogram_fact). Improves query performance for large datasets by reducing data scanned.

```json
"clustering_columns": ["global_session_id"]
```

### `access_groups`
Array of `[group_name, privilege]` pairs defining access control on the report schema and tables. Each entry grants a specific privilege to an Azure Active Directory (AAD) group.

```json
"access_groups": [
  ["<access_group>", "ALL PRIVILEGES"],
  ["<access_group>", "USE SCHEMA"],
  ["<access_group>", "SELECT"],
  ["<access_group>", "EXECUTE"],
  ["<access_group>", "READ VOLUME"],
  ["<admin_group>", "MANAGE"]
]
```

Common privileges: `ALL PRIVILEGES`, `SELECT`, `USE SCHEMA`, `EXECUTE`, `READ VOLUME`, `MANAGE`.

### `schema_managed_location`
Custom storage root location for the schema, different from the catalog's or metastore's default. Uses Azure Blob File System (ABFSS) path format.

```json
"schema_managed_location": "<managed_location>"
```

## Common Configurations

### Development
Minimal config — no access groups or custom storage needed.

```json
"destination": {
  "catalog": "<destination_catalog>",
  "schema": "<destination_schema>",
  "table_prefix": "my_report"
}
```

### Production
Full config with clustering, access groups, and managed storage location.

```json
"destination": {
  "catalog": "<destination_catalog>",
  "schema": "<destination_schema>",
  "table_prefix": "t",
  "clustering_columns": ["global_session_id"],
  "access_groups": [
    ["<access_group>", "ALL PRIVILEGES"],
    ["<access_group>", "USE SCHEMA"],
    ["<access_group>", "SELECT"],
    ["<admin_group>", "MANAGE"]
  ],
  "schema_managed_location": "<managed_location>"
}
```
