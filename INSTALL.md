# Installing Impulse

Customer-facing install guide. For development setup, see [README.md](README.md).

## TL;DR

```bash
git clone https://github.com/<owner>/impulse-app
cd impulse-app
cp profiles.yaml.example profiles.yaml         # only if your silver-layer schema differs from defaults
databricks auth login --host https://<your-workspace>.cloud.databricks.com --profile <name>
./install.sh
```

The script prompts for your UC catalog + schema (where your silver-layer data lives), runs `databricks bundle deploy`, and grants the app's service principal read access to your tables. Five-ish minutes end-to-end.

---

## Prerequisites

### Local tools (on the machine running `install.sh`)

- Databricks CLI (>= 0.290)
- Node.js + npm (>= 18) — `install.sh` builds the React frontend before deploy
- Python 3 (used by `install.sh` for the post-deploy GRANT step)

### Workspace features

Your workspace admin must have enabled:

- **Databricks Apps** (`apps` API surface)
- **Lakebase** (`database` API surface — the app's metadata DB)
- **Serverless SQL Warehouses** (the script creates one)
- **Foundation Model API access** — usually inherited via `EXECUTE` on `system.ai.*` granted to all account users; verify if your workspace has tighter controls
- **User token passthrough** (OBO) — controls whether the app can act as the calling user against SQL + UC. Required.

If any of these is missing, `databricks bundle deploy` will 403 with a clear message naming the feature.

### Your silver-layer data (already in Unity Catalog)

The app reads measurement data from a Unity Catalog schema you provide. Default expected tables:

| Table | Purpose | Required columns (default names) |
|---|---|---|
| `container_metrics` | One row per recording | `container_id`, `start_dt`, `stop_dt` |
| `channel_metrics`   | One row per (container, channel) | `container_id`, `channel_id`, `channel_name`, `min`, `max`, `mean`, `sample_count`, `sample_rate` |
| `channels`          | Per-sample time-series data | `container_id`, `channel_id`, `tstart`, `value` (and `tend` for RLE) |
| `container_tags`    | Container metadata (key/value) | `container_id`, `key`, `value` (optional — set `container_tags_table: null` to synthesize) |
| `channel_tags`      | Channel metadata (key/value) | (optional — synthesized if `channel_tags_table: null`) |
| `<your alias table>`| Friendly name → physical signal lookup | (optional — set `aliases_table` if you have one) |

If your column names or table names differ from the defaults, **copy `profiles.yaml.example` to `profiles.yaml`** at the repo root and uncomment the fields that need overrides. Every field has a default that produces upstream impulse-app behavior, so a minimal profile usually only sets `name:` and a few column overrides. The full field reference is in `profiles.yaml.example` and `server/schema_profile.py`.

### MDF4 ingest pipeline (optional)

If you'll use the in-app MF4 ingest feature, you also need:

- A UC volume containing your raw `.mf4` files (configured per-run from the wizard UI)
- A target catalog + schema where ingest will write — same as your silver-layer schema is fine; ingest also creates a `mdf4_checkpoint` volume in that schema
- Workspace user permissions: `USE CATALOG`, `USE SCHEMA`, `CREATE VOLUME`, `CREATE TABLE` on the target schema (the user triggering ingest needs these — their OBO token is used)

If you're using already-ingested silver-layer data (i.e., you skip the ingest UI), this section doesn't apply.

### Permissions on the target catalog

Your workspace admin needs at least one of:

- `USE CATALOG` + the right to `GRANT` on the catalog + schema (so `install.sh` can issue the SP grants), OR
- The deploying user is the catalog/schema owner

`install.sh` runs four GRANT statements as the authenticated user. If you don't have GRANT permission, the script will fail at the post-deploy step; the bundle resources will already be created but the SP won't have data access until the grants are run manually by someone who does.

---

## What `install.sh` does, step by step

1. **Reads or prompts** for: UC catalog, UC schema, workspace group with app access. Persists answers to `.install.config` for re-runs.

2. **Runs `databricks bundle deploy`** — creates, in your workspace:
   - Lakebase instance named `impulse-v3` (default; configurable in `databricks.yml`'s `app_name` variable)
   - Logical Postgres database `databricks_postgres.impulse.*` for app metadata (user settings, saved reports)
   - SQL warehouse named `impulse-v3` (Medium, serverless, 10-min auto-stop)
   - The app `impulse-v3`, with resource bindings that auto-provision the app's service principal as a Postgres role with `CONNECT + CREATE` on the database, and `CAN_USE` on the warehouse
   - All `permissions` blocks granting your chosen end-user group `CAN_USE` on the app + warehouse

3. **Fetches** the app's service principal client ID from the deployed app.

4. **Runs four SQL GRANT statements** via the bundle-created warehouse:
   ```sql
   GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
   GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
   GRANT SELECT ON ALL TABLES IN SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
   GRANT SELECT ON FUTURE TABLES IN SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
   ```

5. **Prints** the app URL and a reminder about end-user grants (see below).

---

## End-user grants (one-time, by your workspace admin)

After install, end users need (one-time, granted at the same level for whichever workspace group `install.sh` set as `end_user_group` — default `users`):

- `USE CATALOG` on the catalog you chose
- `USE SCHEMA` on the schema you chose
- `SELECT` on the silver-layer tables they need to read

The bundle has already granted that group `CAN_USE` on the app + warehouse, so you only need the UC table-level grants. If your workspace already grants `SELECT ON ALL TABLES IN SCHEMA` to all account users (common for data-team-owned schemas), this is a no-op.

---

## Probing prereqs without deploying

```bash
./install.sh --check
```

Runs read-only API probes against your authenticated workspace to confirm Apps + Lakebase + warehouses + FMAPI are all enabled and that your target catalog/schema exist (if `IMPULSE_CATALOG` / `IMPULSE_SCHEMA` are set). Exits non-zero with a count of failed checks. Useful in CI before doing a real deploy.

## Non-interactive / CI install

```bash
export IMPULSE_CATALOG=my_catalog
export IMPULSE_SCHEMA=my_schema
export IMPULSE_END_USER_GROUP=data-users
./install.sh
```

`install.sh` reads these env vars and skips the prompts.

---

## Re-running / upgrading

`./install.sh` is idempotent: `databricks bundle deploy` is idempotent (no destroy/recreate of Lakebase data), and the four SQL GRANTs are idempotent (re-granting is a no-op).

When you `git pull` a new version of the app, just re-run `./install.sh`.

---

## Troubleshooting

**`PERMISSION_DENIED: feature is not enabled for organization …`** — your workspace doesn't have the required feature flag. Check the Prerequisites section. Common culprits: user token passthrough (OBO), Lakebase.

**`HTTP 403 ... You do not have GRANT ON CATALOG`** — your authenticated user doesn't have permission to grant on the customer catalog. Either authenticate as a user with grant rights, or have your admin run the four GRANT statements that `install.sh` printed.

**`Invalid update mask. ... resources[N].sql_warehouse.id`** — happens if you try to change the bundle-created warehouse's binding on an existing app. The Databricks Apps API forbids editing certain binding fields. Solution: delete the app (`databricks apps delete impulse-v3`), wait for `DELETING` to clear, then re-run `install.sh`.

**`openpgp: key expired`** — the CLI's bundled Terraform binary has an expired signing key. `install.sh` already sets `DATABRICKS_BUNDLE_ENGINE=direct` to work around this; if you see it anyway, you may be running an older CLI — try `databricks --version` and upgrade if it's significantly behind 0.290.0.

**App appears but compute stays `STOPPED`** — `databricks bundle deploy` creates the app shell but doesn't start it. Start the app from the Databricks Apps UI (or `databricks apps deploy impulse-v3 --source-code-path …` — not needed in the bundle flow). The first start takes a few minutes while compute provisions.

**`profiles.yaml` not picked up** — make sure it's named exactly `profiles.yaml` (no `.example` suffix), at the repo root. `git status` should NOT show it (it's gitignored locally; the bundle uploads it from your working tree).
