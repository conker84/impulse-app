# Event Signal Support — Implementation Plan

## Background

The MDA/impulse framework supports **Events** as boolean time-series expressions that segment continuous data into meaningful intervals. Events act as optional filters on aggregations, scoping histogram/statistics computations to specific conditions (e.g. "engine temp above 90C", "moment of engine start").

Events are currently **not properly supported** in the impulse app. The Statistics builder has a dropdown that lists raw channels (wrong — should list defined events). Histograms and 2D Histograms have no event support in the UI at all. Code generation only handles events for Statistics.

This plan adds Events as a first-class concept across the entire app.

---

## Framework Fundamentals

### Event Output Types

Events produce one of two fundamentally different output types:

| Category | Output Type | Expression Example |
|---|---|---|
| Threshold (single) | **Intervals** | `signals["Eng_Temp"] > 90` |
| Compound threshold | **Intervals** | `(signals["Eng_Temp"] > 90) & (signals["RPM"] > 5000)` |
| Rising Edges | **PointsInTime** | `(signals["Eng_Running"] > 0).rising_edges()` |
| Falling Edges | **PointsInTime** | `(signals["Eng_Running"] > 0).falling_edges()` |
| Change Points | **PointsInTime** | `signals["Gear"].change_points(from_state=2, to_state=3)` |

### Aggregation Compatibility

**Verified against framework source code** — the framework has zero runtime validation but silently crashes or produces wrong results for incompatible combinations:

| Event Output Type | Duration Histogram | Distance Histogram | 2D Histogram | Statistics |
|---|---|---|---|---|
| **Intervals** | OK | OK | OK | OK |
| **PointsInTime** | CRASH (no `.tends`) | CRASH | CRASH | CRASH (wrong data format) |

**PointsInTime events cannot be used with any aggregation type** in the current framework. They would require an `event_count` agg_type which does not exist in the framework despite being previously documented in skill docs (now removed).

**PointsInTime events ARE useful** for virtual signal expressions:
- `temperature.where(engine_start_events)` produces a PitSeries (values at event points)
- `start_points.flipflop(stop_points)` converts PointsInTime to Intervals
- `points.expand(width=5.0)` expands points into Intervals of given width

### Code Generation Pattern

For all aggregation types, the framework requires:
```python
event = BasicEvent(name="high_temp", expr=signals["Eng_Temp"] > 90)
my_report.add_event(event)  # Must register with report

page.add_aggregation(Histogram(
    ...,
    event=event,  # Optional filter
))
```

Events used in aggregations MUST be registered with the report via `add_event()` before `determine_report()` is called, or a `ValueError` is raised.

---

## Design Decisions

1. **Events are a separate first-class concept** — stored in their own list, not mixed with virtual signals
2. **All five event types supported** in the Channels tab UI (interval, compound, rising_edges, falling_edges, change_points)
3. **Only Interval events selectable in aggregation dropdowns** — PointsInTime events exist for use in virtual signal expressions only
4. **Compound events** (multiple threshold conditions with AND/OR) supported from day one
5. **Change points** require both `from_state` and `to_state` (both required fields)
6. **Event names** are user-provided, with a blocker preventing save if name is empty
7. **Incompatibility enforcement**: UI blocks selecting PointsInTime events in aggregation dropdowns; if somehow set, code generation should also validate
8. **Field rename**: `event_signal_ref` (which pointed to a raw channel) becomes `event_ref` (which points to an EventDefinition by name)

---

## Data Model

### Python (`server/models.py`)

```python
class ThresholdCondition(BaseModel):
    signal_ref: str        # var_name of a defined signal
    operator: str          # ">", "<", ">=", "<=", "==", "!="
    value: float           # threshold value

class EventDefinition(BaseModel):
    name: str
    event_type: Literal["interval", "rising_edges", "falling_edges", "change_points"]
    # For interval & edge events (threshold-based conditions)
    conditions: list[ThresholdCondition] = []
    compound_logic: Literal["AND", "OR"] = "AND"
    # For change_points only
    signal_ref: str | None = None       # which signal to detect state changes on
    from_state: float | None = None
    to_state: float | None = None
    description: str = ""
```

- `interval` type uses `conditions` (1+ threshold conditions combined with `compound_logic`)
- `rising_edges` / `falling_edges` use `conditions` (threshold condition(s) whose edges are detected)
- `change_points` uses `signal_ref` + `from_state` + `to_state`

### Generated Expression Examples

| Event Type | Conditions / Fields | Generated Expression |
|---|---|---|
| interval (single) | `[{Eng_Temp, >, 90}]` | `signals["Eng_Temp"] > 90` |
| interval (compound AND) | `[{Eng_Temp, >, 90}, {RPM, >, 5000}]` | `(signals["Eng_Temp"] > 90) & (signals["RPM"] > 5000)` |
| interval (compound OR) | `[{Eng_Temp, >, 90}, {RPM, >, 5000}]` | `(signals["Eng_Temp"] > 90) \| (signals["RPM"] > 5000)` |
| rising_edges (single) | `[{Eng_Running, >, 0}]` | `(signals["Eng_Running"] > 0).rising_edges()` |
| rising_edges (compound) | `[{Eng_Temp, >, 90}, {RPM, >, 5000}]` | `((signals["Eng_Temp"] > 90) & (signals["RPM"] > 5000)).rising_edges()` |
| falling_edges | `[{Eng_Running, >, 0}]` | `(signals["Eng_Running"] > 0).falling_edges()` |
| change_points | `signal_ref=Gear, from=2, to=3` | `signals["Gear"].change_points(from_state=2, to_state=3)` |

### State Changes

In `ReportState`:
```python
events: list[EventDefinition] = []  # NEW field
```

On aggregation models:
- `Histogram1DDefinition`: rename `event_signal_ref` to `event_ref`
- `Histogram2DDefinition`: add `event_ref: str | None = None`
- `StatisticsDefinition`: rename `event_signal_ref` to `event_ref`

### TypeScript (`frontend/src/types.ts`)

Mirror all Python model changes with equivalent TS interfaces.

---

## Implementation Steps

### Step 1: Backend Models (`server/models.py`)

- Add `ThresholdCondition` and `EventDefinition` models
- Add `events: list[EventDefinition] = Field(default_factory=list)` to `ReportState`
- Rename `event_signal_ref` → `event_ref` on `Histogram1DDefinition` and `StatisticsDefinition`
- Add `event_ref: str | None = None` to `Histogram2DDefinition`

### Step 2: Backend API (`server/routes/state.py`)

New endpoints:
- `POST /add-event/{session_id}` — create event definition
- `PUT /event/{session_id}/{event_name}` — update event definition
- `DELETE /event/{session_id}/{event_name}` — delete event definition (also clears `event_ref` from any aggregation referencing it)

Update existing endpoints:
- `POST /add-histogram/{session_id}` — accept `event_ref` instead of `event_signal_ref`
- `PUT /aggregation/{session_id}/{name}` — accept `event_ref`
- `POST /add-histogram-2d/{session_id}` — accept `event_ref`
- `POST /add-statistics/{session_id}` — accept `event_ref` instead of `event_signal_ref`

Validation in API layer:
- `event_ref` must reference an existing event name in `state.events`
- For histograms and 2D histograms: referenced event must have `event_type == "interval"` (Intervals output)
- For statistics: any event type is allowed (even though PointsInTime currently crashes in framework, this keeps the door open)

Actually — per framework findings, PointsInTime events crash with Statistics too. So: **only Interval events allowed for all aggregation types**. The dropdown filter handles this in the UI; the API validates as a safety net.

### Step 3: Code Generation (`server/code_generator.py`)

New helper function:
```python
def _generate_event_expr(event: EventDefinition) -> str:
    """Generate the BasicEvent expression string from an EventDefinition."""
```

This produces the correct Python expression based on `event_type`, `conditions`, `compound_logic`, etc. (see Generated Expression Examples above).

Changes to aggregation code generation:
- **Before signals cell**: generate event definitions as named variables
- **Deduplicate**: if multiple aggregations reference the same event, generate the BasicEvent once
- **Register**: call `my_report.add_event(event_var)` for each unique event
- **All aggregation types** (histogram, histogram2d, statistics) pass `event=event_var` when an `event_ref` is set
- **No event**: statistics still use `ContainerEvent` (current behavior); histograms simply omit the `event` parameter

### Step 4: Frontend Types (`frontend/src/types.ts`)

Add interfaces:
```typescript
interface ThresholdCondition {
  signal_ref: string;
  operator: ">" | "<" | ">=" | "<=" | "==" | "!=";
  value: number;
}

interface EventDefinition {
  name: string;
  event_type: "interval" | "rising_edges" | "falling_edges" | "change_points";
  conditions: ThresholdCondition[];
  compound_logic: "AND" | "OR";
  signal_ref: string | null;
  from_state: number | null;
  to_state: number | null;
  description: string;
}
```

Update `ReportState` to include `events: EventDefinition[]`.
Rename `event_signal_ref` → `event_ref` on all aggregation interfaces.
Add `event_ref: string | null` to `Histogram2DDefinition`.

### Step 5: Frontend API (`frontend/src/api.ts`)

Add functions:
- `addEvent(sessionId, payload)` → POST
- `updateEvent(sessionId, eventName, payload)` → PUT
- `deleteEvent(sessionId, eventName)` → DELETE

Update existing functions:
- `addHistogram`, `updateHistogram` → use `event_ref`
- `addStatistics` → use `event_ref`
- Add `event_ref` to 2D histogram functions

### Step 6: Channels Tab UI (`frontend/src/components/SignalsTab.tsx`)

Add a new **Events** section below the virtual signals section:

**Events list:**
- Table showing defined events with columns: Name, Type (badge: Interval/Rising/Falling/Change), Expression summary, Description
- Each row has Edit and Delete buttons
- Visual indicator of output type: "Intervals" badge (green) or "PointsInTime" badge (blue)

**"+ Add Event" button** (same style as "+ Add Virtual Signal"):
- Opens an inline form card

**Event form:**
- **Name** field (required, blocks save if empty)
- **Event Type** dropdown: Interval | Rising Edges | Falling Edges | Change Points
- **Conditional section** based on type:
  - **Interval / Rising Edges / Falling Edges:**
    - Condition rows, each with: signal dropdown + operator dropdown + threshold input + remove button
    - "+ Add Condition" button (for compound events)
    - AND/OR toggle (shown only when 2+ conditions exist)
  - **Change Points:**
    - Signal dropdown
    - From State input (number, required)
    - To State input (number, required)
- **Description** field (optional)
- **Add / Cancel** buttons

### Step 7: Aggregation Builders

**All three builders** (HistogramBuilder, 2D Histogram builder, StatisticsBuilder):
- Add "Event (optional)" dropdown
- Populate ONLY with Interval-type events from `state.events` (filter: `event_type === "interval"`)
- Show "(no events defined)" disabled option if no interval events exist
- Show "None" as default (no event filter)
- The dropdown label should read "Event Filter (optional)"

**StatisticsBuilder** specifically:
- REPLACE the current "Event Signal" dropdown (which lists raw channels) with the new event-only dropdown
- Update helper text from "If set, statistics are computed at event trigger points only." to "If set, statistics are computed only within the event's time intervals."

**HistogramBuilder**:
- Add the event dropdown (currently missing entirely)

**2D Histogram builder**:
- Add the event dropdown (currently missing entirely)

### Step 8: Aggregation Display Cards (`AggregationsTab.tsx`)

All aggregation cards should show the event reference if set:
- Display: `Event: <event_name>` with the event type badge

### Step 9: Agent Tools (`server/agent.py`)

New tool:
- `add_event(name, event_type, conditions?, compound_logic?, signal_ref?, from_state?, to_state?, description?)` — creates an event definition

Update existing tools:
- `add_histogram` — replace `event_signal_ref` param with `event_ref` (references event name)
- `add_statistics` — replace `event_signal_ref` param with `event_ref`
- `add_histogram_2d` — add `event_ref` param

### Step 10: Skills Documentation

**`skills/define-channels/SKILL.md`:**
- Add section documenting event creation via `add_event` tool
- Document all five event types with examples
- Explain that PointsInTime events are for virtual signal expressions, Interval events for aggregation filtering

**`skills/define-aggregations/SKILL.md`:**
- Update `add_histogram` tool call to show `event_ref` (replaces removed `event_signal_ref`)
- Update `add_statistics` tool call to show `event_ref`
- Update `add_histogram_2d` tool call to show `event_ref`
- Add note: only Interval events can be used with aggregations
- Update statistics reference doc (`statistics_types.md`) to use `event_ref` instead of `event_signal_ref`

---

## What We Removed

The following incorrect references were removed from skill docs (already done):

- **`event_count` histogram sub-type** from `SKILL.md` — not supported by framework (PointsInTime events crash at runtime with `AttributeError` on `.tends`)
- **`event_signal_ref` parameter** from `add_histogram` tool call in `SKILL.md`
- **Event Count section** from `histogram_1d_types.md` — entire section with constructor example and documentation
- **Decision tree entry** for "What values at specific events?" → event_count
- **Signal type compatibility entry** for event_count

---

## Out of Scope

- Adding `event_count` as a histogram agg_type (requires framework changes)
- Converting PointsInTime to Intervals automatically (expand/flipflop) — users can do this manually via virtual signals
- Backward compatibility with saved sessions using old `event_signal_ref` field
- Framework-level validation for event/aggregation compatibility
