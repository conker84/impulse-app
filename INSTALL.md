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

The script prompts for the workspace group that should get app access, then runs `databricks bundle deploy` to create the Lakebase instance, SQL warehouse, and app. Five-ish minutes end-to-end. The app reads your silver-layer data as the logged-in user (OBO), so there are no service-principal grants to issue at install time.

---

## Prerequisites

### Local tools (on the machine running `install.sh`)

- Databricks CLI (>= 0.290)
- Node.js + npm (>= 18) — `install.sh` builds the React frontend before deploy
- Python 3 (used by `install.sh` to parse `databricks.yml` and the app URL)

### Workspace features

Your workspace admin must have enabled:

- **Databricks Apps** (`apps` API surface)
- **Lakebase** (`database` API surface — the app's metadata DB)
- **Serverless SQL Warehouses** (the script creates one)
- **Foundation Model API access** — usually inherited via `EXECUTE` on `system.ai.*` granted to all account users; verify if your workspace has tighter controls
- **User token passthrough** (OBO) — controls whether the app can act as the calling user against SQL + UC. Required.

If any of these is missing, `databricks bundle deploy` will 403 with a clear message naming the feature.

### Your silver-layer data (already in Unity Catalog)

The app reads measurement data from a Unity Catalog schema. You pick the catalog + schema **in the app UI at runtime** — they are not set at install time. Default expected tables:

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

**None needed at deploy time.** The app queries your silver-layer tables as the *logged-in user* via their OBO token, so `install.sh` issues no Unity Catalog grants and the deploying user needs no `GRANT` rights on the customer catalog. Data access is governed entirely by each end user's own UC permissions — see [End-user access](#end-user-access-one-time-by-your-workspace-admin) below.

---

## What `install.sh` does, step by step

1. **Reads or prompts** for the workspace group that should get app access. Persists the answer to `.install.config` for re-runs.

2. **Runs `databricks bundle deploy`** — creates the following in your workspace (all named after the `app_name` variable in `databricks.yml`; this repo's default is `impulse-v3`):
   - Lakebase instance `impulse-v3`
   - Logical Postgres database `databricks_postgres.impulse.*` for app metadata (user settings, saved reports)
   - SQL warehouse `impulse-v3` (Medium, serverless, 10-min auto-stop)
   - The app `impulse-v3`, with resource bindings that auto-provision the app's service principal as a Postgres role with `CONNECT + CREATE` on the database, and `CAN_USE` on the warehouse
   - All `permissions` blocks granting your chosen end-user group `CAN_USE` on the app + warehouse

3. **Runs `databricks bundle run`** to start the app, then **prints** the app URL and a reminder about end-user access (see below).

> The app's service principal is never granted access to your silver-layer tables — it doesn't query them. All data reads happen as the logged-in user (OBO).

---

## End-user access (one-time, by your workspace admin)

The app reads silver-layer data as the **logged-in user** (OBO), so each end user needs their own Unity Catalog permissions on the data — this is the *only* data access path (the app's service principal never queries your tables):

- `USE CATALOG` on the silver-layer catalog
- `USE SCHEMA` on the silver-layer schema
- `SELECT` on the silver-layer tables they need to read

Grant these to whichever workspace group you set as `end_user_group` (default `users`). The bundle has already granted that group `CAN_USE` on the app + warehouse. If your workspace already grants `SELECT ON ALL TABLES IN SCHEMA` to all account users (common for data-team-owned schemas), this is a no-op.

---

## Probing prereqs without deploying

```bash
./install.sh --check
```

Runs read-only API probes against your authenticated workspace to confirm Apps + Lakebase + warehouses + FMAPI are all enabled and `npm` is available. Exits non-zero with a count of failed checks. Useful in CI before doing a real deploy.

## Non-interactive / CI install

```bash
export IMPULSE_END_USER_GROUP=data-users
./install.sh
```

`install.sh` reads this env var and skips the prompt.

---

## Re-running / upgrading

`./install.sh` is idempotent: `databricks bundle deploy` is idempotent (no destroy/recreate of Lakebase data).

When you `git pull` a new version of the app, just re-run `./install.sh`.

---

## Troubleshooting

**`PERMISSION_DENIED: feature is not enabled for organization …`** — your workspace doesn't have the required feature flag. Check the Prerequisites section. Common culprits: user token passthrough (OBO), Lakebase.

**`User does not have permission to add resource lakebase to app … (403 PERMISSION_DENIED)`** — the deploying user needs `CAN_MANAGE` on the Lakebase **database instance** being bound to the app. The instance's creator has this automatically; if it was pre-provisioned by someone else, have its owner/an admin grant you `CAN_MANAGE` on the instance (Databricks → Compute → Database Instances → the instance → Permissions), or deploy with an `app_name` whose instance doesn't exist yet so the bundle creates it under your identity.

**`Invalid update mask. ... resources[N].sql_warehouse.id`** — happens if you try to change the bundle-created warehouse's binding on an existing app. The Databricks Apps API forbids editing certain binding fields. Solution: delete the app (`databricks apps delete impulse-v3`), wait for `DELETING` to clear, then re-run `install.sh`.

**`openpgp: key expired`** — the CLI's bundled Terraform binary has an expired signing key. `install.sh` already sets `DATABRICKS_BUNDLE_ENGINE=direct` to work around this; if you see it anyway, you may be running an older CLI — try `databricks --version` and upgrade if it's significantly behind 0.290.0.

**App appears but compute stays `STOPPED`** — `databricks bundle deploy` creates the app shell; `install.sh` then runs `databricks bundle run` to start it. If it's still stopped, start the app from the Databricks Apps UI. The first start takes a few minutes while compute provisions.

**`profiles.yaml` not picked up** — make sure it's named exactly `profiles.yaml` (no `.example` suffix), at the repo root. `git status` should NOT show it (it's gitignored locally; the bundle uploads it from your working tree).
