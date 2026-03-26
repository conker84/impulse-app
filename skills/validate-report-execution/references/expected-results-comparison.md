# Expected vs Actual Results Comparison

Compare report output against a reference (expected) result set provided by the user.

## Table Schema

Both expected and actual tables share the same schema:

**Dimension table** (`_histogram_dimension`):

| Column | Type | Join Key |
|---|---|---|
| `visual_id` | int | Primary key — links to fact table |
| `name` | string | Histogram name — used to match across expected/actual |
| `type` | string | `duration`, `distance`, `durationCount`, `eventCount` |
| `bins` | array\<double\> | Bin edges |
| `bins_unit` | string | Unit label |

**Fact table** (`_histogram_fact`):

| Column | Type | Join Key |
|---|---|---|
| `global_session_id` | string | Session identifier |
| `visual_id` | int | Links to dimension table |
| `bin_ID` | int | Bin index within the histogram |
| `hist_value` | double | Computed value (duration in seconds, distance in km, count) |
| `lower_bound` | double | Lower edge of the bin |
| `upper_bound` | double | Upper edge of the bin |

## Join Strategy

Expected and actual tables come from **different reports**, so `visual_id` values will differ. Join on **histogram name** via the dimension tables, then match bins by `bin_ID` (or `lower_bound`/`upper_bound`), and sessions by `global_session_id`.

## Comparison Queries

### Step 1: Match histograms by name

Find which histograms exist in both expected and actual, and which are missing:

```sql
SELECT
    COALESCE(e.name, a.name) AS histogram_name,
    e.name IS NOT NULL AS in_expected,
    a.name IS NOT NULL AS in_actual,
    e.type AS expected_type,
    a.type AS actual_type
FROM <expected_dim> e
FULL OUTER JOIN <actual_dim> a ON e.name = a.name
ORDER BY histogram_name
```

**Interpretation:**
- `in_expected = true, in_actual = true` — matched, proceed to value comparison
- `in_expected = true, in_actual = false` — histogram missing from actual results
- `in_expected = false, in_actual = true` — extra histogram in actual (new, not in reference)

### Step 2: Aggregated comparison per histogram

Compare total values across all sessions and bins for each matched histogram:

```sql
WITH expected_agg AS (
    SELECT
        ed.name AS histogram_name,
        SUM(ef.hist_value) AS expected_total,
        COUNT(DISTINCT ef.global_session_id) AS expected_sessions,
        COUNT(DISTINCT ef.bin_ID) AS expected_bins_with_data
    FROM <expected_fact> ef
    JOIN <expected_dim> ed ON ef.visual_id = ed.visual_id
    WHERE ef.hist_value > 0
    GROUP BY ed.name
),
actual_agg AS (
    SELECT
        ad.name AS histogram_name,
        SUM(af.hist_value) AS actual_total,
        COUNT(DISTINCT af.global_session_id) AS actual_sessions,
        COUNT(DISTINCT af.bin_ID) AS actual_bins_with_data
    FROM <actual_fact> af
    JOIN <actual_dim> ad ON af.visual_id = ad.visual_id
    WHERE af.hist_value > 0
    GROUP BY ad.name
)
SELECT
    COALESCE(e.histogram_name, a.histogram_name) AS histogram_name,
    e.expected_total,
    a.actual_total,
    CASE
        WHEN e.expected_total > 0
        THEN ROUND(ABS(a.actual_total - e.expected_total) / e.expected_total * 100, 2)
        ELSE NULL
    END AS deviation_pct,
    e.expected_sessions,
    a.actual_sessions,
    e.expected_bins_with_data,
    a.actual_bins_with_data
FROM expected_agg e
FULL OUTER JOIN actual_agg a ON e.histogram_name = a.histogram_name
ORDER BY histogram_name
```

**Interpretation:**

| `deviation_pct` | Verdict |
|---|---|
| 0% | Exact match |
| < 1% | Effectively identical (floating point tolerance) |
| 1–5% | Minor deviation — likely due to different session sets or solver precision |
| 5–20% | Significant deviation — investigate (different time range, missing sessions) |
| > 20% | Major deviation — likely a bug in signal definitions or bin configuration |
| NULL (expected has data, actual doesn't) | Histogram produced no results — signal or enable condition issue |

### Step 3: Per-session per-bin comparison

For histograms with significant deviation, drill down to per-session per-bin level. Only run this for specific histograms flagged in Step 2.

```sql
WITH matched AS (
    SELECT ed.visual_id AS e_vid, ad.visual_id AS a_vid, ed.name
    FROM <expected_dim> ed
    JOIN <actual_dim> ad ON ed.name = ad.name
    WHERE ed.name = '<histogram_name>'
)
SELECT
    m.name AS histogram_name,
    ef.global_session_id,
    ef.bin_ID,
    ef.lower_bound,
    ef.upper_bound,
    ef.hist_value AS expected_value,
    af.hist_value AS actual_value,
    ROUND(af.hist_value - ef.hist_value, 6) AS abs_diff,
    CASE
        WHEN ef.hist_value > 0
        THEN ROUND((af.hist_value - ef.hist_value) / ef.hist_value * 100, 2)
        ELSE NULL
    END AS rel_diff_pct
FROM <expected_fact> ef
JOIN matched m ON ef.visual_id = m.e_vid
LEFT JOIN <actual_fact> af
    ON af.visual_id = m.a_vid
    AND af.global_session_id = ef.global_session_id
    AND af.bin_ID = ef.bin_ID
WHERE ef.hist_value > 0 OR af.hist_value > 0
ORDER BY ef.global_session_id, ef.bin_ID
LIMIT 100
```

### Step 4: Identify sessions only in one side

Find sessions present in expected but missing from actual (or vice versa):

```sql
WITH expected_sessions AS (
    SELECT DISTINCT ef.global_session_id
    FROM <expected_fact> ef
    JOIN <expected_dim> ed ON ef.visual_id = ed.visual_id
    WHERE ed.name = '<histogram_name>'
),
actual_sessions AS (
    SELECT DISTINCT af.global_session_id
    FROM <actual_fact> af
    JOIN <actual_dim> ad ON af.visual_id = ad.visual_id
    WHERE ad.name = '<histogram_name>'
)
SELECT
    COALESCE(e.global_session_id, a.global_session_id) AS global_session_id,
    e.global_session_id IS NOT NULL AS in_expected,
    a.global_session_id IS NOT NULL AS in_actual
FROM expected_sessions e
FULL OUTER JOIN actual_sessions a ON e.global_session_id = a.global_session_id
WHERE e.global_session_id IS NULL OR a.global_session_id IS NULL
ORDER BY global_session_id
```

This is the most common cause of aggregated deviations — different session sets due to different vehicle/time filters.

## Common Deviation Causes

| Deviation Pattern | Likely Cause |
|---|---|
| All histograms deviate by the same % | Different number of sessions (time range or vehicle filter) |
| One histogram deviates, others match | Signal definition differs (alias, masking, filter) |
| Values are proportionally scaled | Unit conversion issue (e.g. seconds vs nanoseconds) |
| Bin distribution shifted | Bin boundaries differ (check `bins` in dimension table) |
| Some sessions missing from actual | Start/stop timestamp filter excludes sessions present in expected |
| Exact match on overlapping sessions, total differs | Additional sessions in one side — not a bug, just scope difference |
