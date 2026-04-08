# Impulse Demo: Cooling System Failure on an Alpine Test Loop

## Scenario

A durability test engineer at VW is reviewing data from a **cooling system validation
test drive** of a next-gen **Golf GTI prototype**. The team redesigned the cooling system
for the higher-output engine and needs to confirm it can handle sustained load in hot
conditions. The test loop runs from Garmisch-Partenkirchen up over the Karwendel pass
and back — a standard Alpine validation route.

The driver reported the **coolant temperature warning light** came on during the climb.
The engineer uses Impulse to investigate.

**The drive (45-minute Alpine loop):**

| Phase | Time | What happens |
|-------|------|--------------|
| Town warmup | 0–5 min | Cold start from Garmisch, idle and low speed. Coolant warms from 40 → 85 °C |
| Highway cruise | 5–20 min | B2 toward Mittenwald, steady 120 km/h at ~2500 RPM. Coolant stable around 88 °C |
| **Mountain climb** | 20–30 min | Karwendel pass — road climbs, speed drops to 50–70 km/h. Driver floors it: RPM hits 4500+, throttle >80%, **engine load >85%**. Coolant rises to 108–112 °C. Oil temp follows with a ~60 s lag. |
| Descent | 30–38 min | Downhill engine braking, low throttle. Coolant recovers to 90 °C |
| Highway return | 38–45 min | Back to Garmisch, normal cruise, all temps stable |

**Channels (7 signals):**

| # | Channel Name | Unit | Role in story |
|---|-------------|------|---------------|
| 1 | Engine Speed | RPM | Load indicator — spikes during climb |
| 2 | Vehicle Speed | km/h | Drops on the mountain despite high RPM |
| 3 | Coolant Temperature | °C | **The problem** — overheats on the climb |
| 4 | Oil Temperature | °C | Confirms thermal stress, lags coolant by ~60 s |
| 5 | Throttle Position | % | Shows driver intent — wide open on climb |
| 6 | Intake Pressure | kPa | High during climb = high engine load |
| 7 | Engine Load | % | **The smoking gun** — directly shows the sustained high-load condition |

**Data location:** `maximhammer_catalog.impulse_moon` (1 container, 7 channels)

---

## Demo Script

### Step 1 — Create a New Report (Source Data)

1. Open the app → click **"New Report"**
2. In **Source Data**, configure:
   - **Catalog:** `maximhammer_catalog`
   - **Schema:** `impulse_moon`
3. Click **Next**

> **Talking point:** *"Impulse connects directly to your Unity Catalog silver layer.
> No data movement — the data stays in Delta Lake and we query it in place."*

---

### Step 2 — Name & Vehicles

1. Set report name: **"Alpine Cooling Validation — Golf GTI"**
2. In **Vehicles**, select the VW Golf GTI container
3. Click **Next**

> **Talking point:** *"Each container is a test drive session. The metadata —
> vehicle, route, test conditions — is all captured automatically during ingestion."*

---

### Step 3 — Define Channels via Chat

1. In the **Channels** step, use the chat to add signals:
   - Type: *"Add Engine Speed, Vehicle Speed, Coolant Temperature, and Throttle Position"*
   - The LLM resolves the names and adds them as physical channels

> **Talking point:** *"Engineers describe what they need in plain English.
> The AI agent searches the channel catalog and resolves the correct physical channels.
> No need to remember exact signal IDs or naming conventions."*

---

### Step 4 — Add Histograms & Run the Report

1. In the **Aggregations** step, add two **Duration Histograms**:

   **Coolant Temperature duration histogram:**
   - Signal: Coolant Temperature
   - Bins: `[40, 60, 70, 80, 85, 90, 95, 100, 105, 110, 115, 120]`
   - Unit: °C

   **Engine Speed duration histogram:**
   - Signal: Engine Speed
   - Bins: `[0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000]`
   - Unit: RPM

2. Click **Deploy & Run** → wait for the job to complete
3. Review the histogram results

> **What the audience sees:**
> - **Coolant Temperature:** Most time at 85–95 °C (normal operating range), but a
>   clear second cluster at 105–115 °C. The car spent real time in the danger zone.
> - **Engine Speed:** Bulk of time at 2000–3000 RPM (highway cruise), but a visible
>   tail at 4000–5500 RPM that shouldn't be there in normal driving.
>
> **Talking point:** *"Two histograms, and the anomaly jumps out immediately. The
> engine ran hot and at unusually high RPM. But when? And why? Let's dig into the
> raw time series."*

---

### Step 5 — Time Series Deep Dive

1. Navigate to the **Time Series Explorer** (sidebar or data sources page)
2. Select catalog `maximhammer_catalog`, schema `impulse_moon`
3. Select the VW Golf GTI container
4. **Load these channels** (select all and click Load):
   - Coolant Temperature
   - Engine Load
   - Engine Speed
   - Intake Pressure
   - Oil Temperature
5. View the full 45-minute overview

> **What the audience sees:** Five signals overlaid with automatic dual y-axis
> grouping by unit. The mountain section (20–30 min) jumps out immediately:
> - **Engine Speed** oscillates wildly between 3500–5500 RPM (the driver is
>   constantly working through gears on the steep mountain road)
> - **Engine Load** tracks the same pattern, swinging 60–100%
> - **Coolant Temperature** climbs relentlessly from 85 → 115+ °C — even though
>   RPM and load dip between peaks, the cooling system never gets a chance to recover
> - **Oil Temperature** follows the same upward trend with a visible ~60 s lag
> - At ~14:30 the descent begins: engine load drops to near zero, and temperatures
>   finally start falling

6. **Zoom in** to the 20–30 min mountain section by click-dragging on the chart
7. Point out the key pattern: engine load and RPM oscillate peak-to-peak, but
   coolant temperature only goes up — the cooling system is overwhelmed by the
   *sustained* heat input, not any single spike

> **Talking point:** *"Look at the contrast: engine speed and load are oscillating —
> the driver is on and off the throttle on every switchback. But coolant temperature
> doesn't oscillate, it just climbs. That tells you the cooling system can't dissipate
> heat fast enough between load cycles. Oil temperature confirms it with a ~60 s lag.
> This is the evidence the cooling system team needs — the radiator and fan strategy
> can't keep up with 10 minutes of sustained mountain load."*

---

### Step 6 — Re-open Report & Add Event Filter via Chat

1. Go back to the report (re-open from the **saved reports** list)
2. Navigate to the **Aggregations** step
3. In the chat, type:

   > *"Please add an event to the report where the engine speed channel
   > is filtered by RPM values greater than 3000"*

4. The LLM creates an **interval event** with expression: `engine_speed > 3000`
5. The event appears in the event list as e.g. `"high_rpm"`

> **Talking point:** *"Natural language to formal event definition. The AI understands
> 'filtered by RPM values greater than 3000' means a threshold-based interval event.
> Events let us slice the data — we can now compute aggregations only during those
> high-load windows, filtering out all the normal highway driving."*

---

### Step 7 — Add 2D Heatmap & Re-Run

1. Still in the **Aggregations** step, add a **2D Histogram**:

   **Engine Speed × Coolant Temperature heatmap:**
   - X-axis: Engine Speed
   - X-bins: `[0, 1000, 2000, 3000, 4000, 5000, 6000]`
   - Y-axis: Coolant Temperature
   - Y-bins: `[40, 60, 80, 90, 95, 100, 105, 110, 120]`
   - Event filter: `high_rpm` (the event from Step 6)

2. Click **Deploy & Run** again → wait for job
3. Review the 2D heatmap results

> **What the audience sees:** A heatmap showing time spent in each RPM × Temperature
> cell. The hot spot is clearly in the **high RPM (4000–5500) + high temp (105–115 °C)**
> quadrant — the dangerous operating region. Normal driving clusters harmlessly at
> **2000–3000 RPM, 85–95 °C**.
>
> **Talking point:** *"The 2D heatmap is an operating point map — it shows exactly which
> conditions overwhelm the cooling system. When RPM exceeds 4000 for more than a few
> minutes, the cooling system can't dissipate the heat fast enough. And because we
> filtered by the high-RPM event, we're only looking at the data that matters.
> This report can now be re-run across the entire test fleet to see if this is a
> one-off or a systemic design issue."*

---

## Key Messages to Land

| Feature | What it demonstrates |
|---------|---------------------|
| **Silver layer integration** | Zero-copy access to Unity Catalog measurement data |
| **Duration Histograms** | Instant anomaly detection — outlier clusters jump out |
| **Time Series Explorer** | Interactive drill-down into massive datasets in <50 ms |
| **Multi-signal overlay** | Correlate cause and effect across 5+ signals with auto-axis grouping |
| **LLM Chat** | Natural language → formal event definitions, no coding required |
| **Event filtering** | Slice aggregations to specific operating conditions |
| **2D Heatmaps** | Operating point maps reveal dangerous condition combinations |
| **Report re-run** | Iterative analysis — add aggregations and re-deploy without starting over |
| **Fleet scalability** | Same report template can run across hundreds of test drives |

