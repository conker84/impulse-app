# Impulse — Browser E2E Testing Guide

Instructions for Claude processes to test the Impulse app via Chrome DevTools MCP tools.

---

## Prerequisites

- App must be deployed (default instance or your own `--instance`, see Deploying below)
- PAT must already be configured in the app's Settings (needed for Deploy & Run)
- If testing in parallel with other agents, read the **Concurrency** section first

## Deploying Your Instance

**Default instance (main session only):**
```bash
.claude/deploy-fevm.sh              # deploys "impulse" app
```
URL: `https://impulse-7474650020296832.aws.databricksapps.com`

**Feature instance (worktree agents):**
```bash
.claude/deploy-fevm.sh --instance feat-a              # deploys "impulse-feat-a" app
.claude/deploy-fevm.sh --instance feat-a --skip-build  # skip frontend build
```
Get the URL after deploy:
```bash
databricks apps get impulse-feat-a --profile fe-vm-maximhammer --output json | python3 -c "import sys,json; print(json.load(sys.stdin).get('url','pending...'))"
```

Each `--instance` gets its own app name, workspace path, and URL. All instances share the same Lakebase DB, warehouse, and LLM endpoint — this is safe because report names provide data isolation.

**First-time instance setup:** The first deploy of a new instance name creates the Databricks App. This takes longer (~5 min) as it provisions the app container. Subsequent deploys are faster. The PAT must be configured via the Settings modal on each new app instance (PAT is stored per-instance in Lakebase, keyed by user email — but the Settings entry happens through the UI).

---

## Concurrency: Multiple Claude Agents

### Deploy isolation: separate app instances

Each agent deploys to its **own app instance** via `--instance`. This gives:
- Separate workspace path (no code sync collisions)
- Separate app container (no server restart interference)
- Separate URL (no session conflicts)

**Rules:**
1. The default instance (`impulse`) is owned by the **main session only**
2. Worktree agents use `--instance {feature-name}` (e.g., `--instance agg-types`, `--instance ts-viewer`)
3. Never deploy to another agent's instance

### Report name isolation: unique names with hex suffix

The report name becomes the **UC table prefix** and the **DAB bundle directory name**. Collisions cause silent overwrites.

**Naming convention:** `test_{feature}_{4_char_hex}`

Generate your suffix at the start of testing:
```bash
python3 -c "import secrets; print(secrets.token_hex(2))"
```

Example: `test_agg_types_a3f1`, `test_hist2d_b7c2`

**What collides if names match:**
- Gold-layer tables (`{prefix}_histogram_fact`, `_histogram_dimension`, `_session_dimension`) in `maximhammer_catalog.impulse`
- Lakebase `saved_reports` row (UNIQUE on `user_email + report_name` — same SSO user for all agents → upsert overwrites)
- DAB scaffold directory (scaffold does `rmtree` before recreating)

### Browser isolation: separate Chrome instances

Chrome DevTools MCP's `select_page` is **global state** — not per-connection. Two agents sharing one Chrome instance will corrupt each other's interactions:

```
Agent A: select_page(Tab1)
Agent B: select_page(Tab2)    ← overwrites global state
Agent A: click(...)           ← hits Tab2 (WRONG!)
```

**Solution: each agent launches its own Chrome instance** with a unique `--userDataDir`. This gives a completely separate Chrome process, DevTools connection, and page state.

**How to set up a separate Chrome instance for your agent:**

Before starting browser testing, launch Chrome DevTools MCP with a unique user data directory. From your worktree, you can use an MCP configuration override or launch manually:

```bash
# Launch a dedicated Chrome instance for this agent
npx chrome-devtools-mcp@latest --userDataDir ~/.vibe/chrome/agent-{your-feature-name}
```

Or use the `--isolated` flag for a temporary profile that auto-cleans:
```bash
npx chrome-devtools-mcp@latest --isolated
```

**Key points:**
- Each `--userDataDir` path spawns a separate Chrome process
- Each Chrome process has independent tabs, cookies, and SSO sessions
- Each agent's MCP tools (`click`, `fill`, `take_snapshot`) only affect their own Chrome instance
- SSO login is required per Chrome instance (separate cookie jars)

**If you cannot launch a separate Chrome instance** (e.g., MCP server is shared), browser testing must be **serialized** — only one agent uses Chrome at a time.

---

## App URLs

**Default instance (main session):**
```
https://impulse-7474650020296832.aws.databricksapps.com
```

**Feature instances:** Get URL via CLI after deploying (see Deploying section above).

## Authentication

The app uses Databricks SSO via Okta. Each Chrome instance needs its own login.

1. Navigate to the app URL
2. Wait for the login page: look for text `"Continue with SSO"` or `"Sign In"`
3. If you see "Continue with SSO" → click it
4. If you see the Okta sign-in form with a username field pre-filled → click the `"Next"` button
5. SSO should complete automatically (session cookie). If prompted for password/MFA, the test cannot proceed without user intervention.
6. Wait for `"Create New Report"` or `"Impulse"` to confirm the app loaded

**Session expiry:** SSO sessions last hours. If you get redirected to login mid-test, re-authenticate the same way.

---

## Test Flow: Full Wizard (Existing Silver Tables)

### Demo values that work on the FEVM workspace

| Field | Value | Notes |
|-------|-------|-------|
| Catalog | `maximhammer_catalog` | Has ingested demo data |
| Schema | `impulse` | Contains all 5 Silver tables |
| Report name | `test_{feature}_{hex}` | Must be lowercase, underscores, no spaces. Generate hex: `python3 -c "import secrets; print(secrets.token_hex(2))"` |
| Description | any string | Optional |
| Creator | any string | Optional |
| Signals available | Engine RPM, Vehicle Speed Sensor, Ambient Air Temperature, Engine Coolant Temperature, etc. | 10 channels total from OBD-II demo data |
| Vehicle | `Seat_Leon` | Only vehicle in the demo dataset, 3 containers |
| Start timestamp | `2024-01-01T00:00` | Before all demo data |

### Step 1: Source Data

```
Action: Click "Create New Report"
Wait for: "Source Data" or "Choose Data Source"

Action: Click button "Existing Silver Tables"
Wait for: "CATALOG" or "Select a catalog"

Action: Fill catalog dropdown → "maximhammer_catalog"
Wait for: "Select a schema" (schema dropdown enables)

Action: Fill schema dropdown → "impulse"
Wait for: "Next Step →" button becomes enabled (not disabled)

Action: Click "Next Step →"
Wait for: "Report Name" or "Step 2"
```

### Step 2: Report Name

```
Action: Fill textbox placeholder="e.g. oil_temp_report" → your unique report name
Action: Fill textbox placeholder="e.g. Oil temperature duration analysis" → description
Action: Fill textbox placeholder="e.g. John Doe" → creator name

Action: Click button "Save Metadata"
Wait for: "Saved" or "Next Step" text, and "Next Step →" becomes enabled

Action: Click "Next Step →"
Wait for: "Channels" or "Step 3"
```

**Important:** The name field must be filled FIRST — it's required. The "Save Metadata" button stays disabled until the name is non-empty.

### Step 3: Channels

```
Wait for: "Browse Channels" and channel checkboxes to appear
  (The app auto-fetches channels from Silver layer on step entry.
   Look for "Discovered N channels" in the chat.)

Action: Click checkbox "Engine RPM" (uid pattern: checkbox containing "Engine RPM")
Action: Click checkbox "Vehicle Speed Sensor" (uid pattern: checkbox containing "Vehicle Speed Sensor")
  (Or any other channels — at least 1 is needed)

Wait for: "Add N Channels" button appears

Action: Click "Add N Channels"
Wait for: "N signal(s) defined" and signal table appears with VARIABLE/TYPE/ALIAS columns

Action: Click "Next Step →"
Wait for: "Aggregations" or "Step 4"
```

**Notes:**
- Already-added channels show "Added" badge and their checkbox becomes disabled
- You can also add signals via the chat input (NL mode), but the checkbox flow is more reliable for automated testing
- The channel list comes from `channel_tags` table — if it's empty, the Silver layer has no data

### Step 4: Aggregations

```
Action: Click button "Duration" (text: "Duration Time spent in each value range")
Wait for: "SIGNAL" dropdown and histogram builder form appears

Action: Fill signal dropdown → "engine_rpm — Engine RPM [RPM]"
  (The dropdown options format: "{var_name} — {channel_name} [{unit}]")

Action: Click button "Auto-fill"
Wait for: Bins textbox gets populated with comma-separated numbers
  (Auto-fill calls the backend which suggests bins based on the signal's data range.
   May take 2-5 seconds. The bins field, unit field, name field, and description
   field all get populated.)

Action: Click button "Add Histogram"
Wait for: "1 histogram(s) defined" and histogram card appears showing name, type, bins info

Action: Click "Next Step →"
Wait for: "Vehicles" or "Step 5"
```

**Notes:**
- 4 histogram types available: Duration, Distance, Duration Count, Event Count
- Auto-fill requires a signal to be selected first — button is disabled otherwise
- Name auto-generates from signal name + type + page number (e.g., `engine_rpm_p1`)
- You can add multiple histograms before advancing
- Manual bin entry: comma-separated numbers like `0, 500, 1000, 1500, 2000`

### Step 5: Vehicles

```
Wait for: "Available Vehicles" section with checkboxes
  (Vehicle candidates are auto-fetched from container_metrics on step entry)

Action: Click checkbox "Seat_Leon" (or "Select all")
Wait for: "Add N Selected Vehicle" button becomes enabled

Action: Click "Add N Selected Vehicle"
Wait for: "N vehicle(s) configured" and vehicle table + data sources section appears

(Optional) Action: Fill start timestamp → "2024-01-01T00:00"
  (The datetime-local input can be tricky — use the fill tool with ISO format.
   Not strictly required for advancing to Ready step.)

Action: Click "Next Step →"
Wait for: "Ready" or "Step 6"
```

**Notes:**
- The vehicle list comes from `container_tags` — shows distinct test_object_name values
- Adding a vehicle auto-configures data sources (container_metrics, channel_metrics, channels tables) and destination (catalog, schema, table_prefix derived from report name)
- Data sources section shows the full table paths — verify they look correct

### Step 6: Ready (Review & Deploy)

```
The review panel shows:
- Report metadata (name, description, creator)
- Compute config (Job Cluster vs All-Purpose Cluster radio buttons)
- Signals table
- Histograms cards
- Vehicles & Data Sources

Buttons available:
- "Save" — saves report definition to Lakebase (can reload later from landing)
- "Deploy & Run" — scaffolds DAB, deploys bundle, submits job
- "Validate" — disabled until job completes
- "← Back" — go to previous step
- "Home" — back to landing screen
```

### Deploy & Run (optional — takes 5-10 minutes)

```
Action: Click "Deploy & Run"
Wait for: "Scaffolding" text appears

Progress indicators:
1. "✓ Scaffolding report" — DAB template generated (~5-10s)
2. "Deploying bundle" — `databricks bundle deploy` running (~60-120s)
3. "✓ Job submitted" — job run created on Databricks
4. "Waiting for deployment to complete..." — polls every 30s

Wait for (long): "completed successfully" or "job failed"
  Timeout: 600000ms (10 minutes) — cluster startup + notebook execution

On success:
- Chat: "Report job completed successfully! You can now validate the results."
- "Validate" button becomes enabled
- "View Results" button may appear (navigates to Visualize view)

On failure:
- Chat: "Report job failed. {error details}"
- Check the Databricks job run URL for notebook error output
```

**Common deploy failures:**
- "Please configure your Personal Access Token in Settings" → PAT not set, opens Settings modal
- Bundle deploy timeout → workspace connectivity issue
- Job fails with "TABLE_OR_VIEW_NOT_FOUND" → Silver tables don't exist or wrong catalog/schema
- Job fails with numpy/asammdf error → library conflict on job cluster (known issue, see PROJECT.md)

### Validate (after successful job)

```
Action: Click "Validate"
Wait for: "Validation passed" or "Validation has issues"

Validation runs 3 levels:
1. Table existence — checks gold-layer tables exist
2. Row counts — checks tables have rows
3. Histogram values — checks histograms have non-zero data
```

### View Results (Visualize)

```
Action: Click "View Results" (appears after successful deploy)
  — OR go to landing screen and click "Visualize" on the saved report

Wait for: "Vehicles" sidebar section and "Histograms" sidebar section

Action: Check histogram checkboxes in sidebar
Action: (Optional) Check vehicle checkboxes for filtering
Action: Click "Show N Histogram(s)" button

Wait for: Plotly chart(s) to render in the main area
```

---

## Quick Smoke Test (No Deploy)

For testing frontend changes without running a job:

1. Navigate to app
2. Authenticate
3. Click "Create New Report"
4. Walk through Steps 1-5 (Source Data → Vehicles)
5. On Step 6, click **Save** (not Deploy)
6. Click **Home** → verify report appears in saved reports list
7. Click **Open** on the saved report → verify state is restored
8. Click **Delete** → verify report is removed

This tests the full wizard flow, state persistence, and Lakebase integration without any Databricks job execution.

---

## Testing the Visualize View (with existing data)

If a report has already been deployed and has gold-layer tables, you can test visualization without redeploying:

1. From landing screen, click **Visualize** on a report that has been previously deployed
2. If tables don't exist → you'll see "Report results not found" error
3. If tables exist → sidebar loads histograms, vehicles, filter ranges
4. Select histograms → click "Show" → charts render

**Known working reports on FEVM:** Check the landing screen for previously deployed reports with data.

---

## Useful Selectors & Patterns

### Button identification
Buttons have descriptive text content. Use the snapshot `uid` values — they change between page loads, so always take a fresh snapshot before clicking.

### Dropdowns (select elements)
Use `fill` with the option's `value` attribute, not `click`. The combobox elements have child `option` elements showing the available values.

### Waiting strategy
- Always `wait_for` after navigation or actions that trigger backend calls
- Use multiple possible texts: `["success text", "error text", "fallback text"]`
- Default timeout (5s) is too short for backend calls — use 10000-15000ms
- For deploy/job completion, use 600000ms (10 minutes)

### Snapshot vs Screenshot
- `take_snapshot` returns the accessibility tree (text, uids, element types) — faster and more reliable for finding elements
- `take_screenshot` returns a visual image — useful for verifying layout, colors, chart rendering
- Prefer snapshot for navigation, screenshot for visual verification

### Common wait texts by step

| Step | Success text | Error text |
|------|-------------|------------|
| Landing → Editor | `"Source Data"`, `"Choose Data Source"` | — |
| Step 1 → 2 | `"Report Name"`, `"Step 2"` | — |
| Step 2 → 3 | `"Channels"`, `"Discovered"` | — |
| Step 3 → 4 | `"Aggregations"`, `"Step 4"` | — |
| Step 4 → 5 | `"Vehicles"`, `"Step 5"` | — |
| Step 5 → 6 | `"Ready"`, `"Deploy & Run"` | — |
| Deploy start | `"Scaffolding"` | `"Please configure"`, `"Deploy error"` |
| Deploy done | `"completed successfully"` | `"job failed"` |
| Validate | `"Validation passed"` | `"Validation has issues"` |

---

## Open Concerns / TODO

### No automated assertion framework
Currently testing is "take snapshot, eyeball the text". There's no structured way to assert "this step succeeded" beyond checking for expected text. Consider:
- A `/api/health` or `/api/test/state` endpoint that returns machine-readable wizard state
- Snapshot-based assertions: save expected snapshots, diff against actual

### Deploy wait time dominates
A full deploy test takes 5-10 minutes (cluster startup + job execution). Three parallel agents = 3 clusters. Mitigations:
- Use the **All-Purpose Cluster** radio button on Step 6 if a cluster is already running (skips startup)
- For most tests, the **Quick Smoke Test** (no deploy) is sufficient
- Only run deploy tests when code generation or template changes are made

### Gold-layer table cleanup is manual
Test runs leave tables in `maximhammer_catalog.impulse.*`. No automatic cleanup. Over time this accumulates. Consider: a cleanup script that drops `test_*` prefixed tables.

### Report name collisions have no app-level enforcement
The app allows duplicate report names that map to the same UC table prefix. Parallel testing relies on naming conventions (hex suffix). **Recommended app change:** validate table prefix uniqueness at scaffold time by checking for existing tables with that prefix.

### datetime-local input is fragile
The timestamp input on Step 5 uses browser-native `datetime-local` which renders differently across OSes. The `fill` tool works with ISO format (`2024-01-01T00:00`) but may not work reliably on all Chrome versions.

### No way to verify chart content programmatically
On the Visualize view, we can check that Plotly charts render (screenshot shows bars), but can't assert on the actual data values without querying the gold-layer tables directly via SQL.

### First-time PAT setup per instance
Each new app instance (`impulse-feat-a`) requires PAT configuration through the Settings modal. This is a manual step that can't easily be automated (requires typing a PAT into a modal). Consider: sharing PAT across instances via the same Lakebase row (keyed by user email, not instance).

---

## Cleanup Checklist

After testing, clean up **all** resources you created:

**Required:**
- [ ] Delete test reports from landing screen (click Delete on the report card)
- [ ] Cancel any still-running jobs in the Databricks workspace (Workflows → Active Runs)

**Required if you ran Deploy & Run:**
- [ ] Drop gold-layer tables (all three):
  ```sql
  DROP TABLE IF EXISTS maximhammer_catalog.impulse.{prefix}_histogram_fact;
  DROP TABLE IF EXISTS maximhammer_catalog.impulse.{prefix}_histogram_dimension;
  DROP TABLE IF EXISTS maximhammer_catalog.impulse.{prefix}_session_dimension;
  ```
- [ ] Delete scaffolded report directory from workspace
- [ ] (Optional) Destroy DAB bundle state:
  ```bash
  cd reports/{user_folder}/{report_name} && databricks bundle destroy -t dev --profile fe-vm-maximhammer --auto-approve
  ```

**If you deployed a feature instance:**
- [ ] (Optional) Delete the app instance when no longer needed:
  ```bash
  databricks apps delete impulse-{instance} --profile fe-vm-maximhammer
  ```
