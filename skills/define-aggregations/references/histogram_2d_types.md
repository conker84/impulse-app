# 2D Histogram Types — Detailed Reference

A 2D histogram (heatmap) shows the correlation between two signals. Each cell accumulates the duration where both signals simultaneously fall into their respective bins.

## Constructor

```python
Histogram2D(
    name="eng_spd_vs_torque_p1",
    x_expr=signals["Eng_Spd_masked"],
    y_expr=signals["Eng_Trq_masked"],
    x_bins=[float(i) for i in range(0, 7000, 500)],
    y_bins=[float(i) for i in range(-50, 600, 50)],
    desc="Engine speed vs. torque operating map",
    x_bins_unit="rpm",
    y_bins_unit="Nm"
)
```

## Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | str | Yes | Unique histogram ID |
| `x_expr` | SampleSeries | Yes | Signal for the x-axis |
| `y_expr` | SampleSeries | Yes | Signal for the y-axis |
| `x_bins` | list[float] | Yes | Bin edges for x-axis |
| `y_bins` | list[float] | Yes | Bin edges for y-axis |
| `desc` | str | No | Human-readable description |
| `x_signal_name` | str | No | Display name for x-axis signal |
| `y_signal_name` | str | No | Display name for y-axis signal |
| `x_bins_unit` | str | No | Unit for x-axis bins |
| `y_bins_unit` | str | No | Unit for y-axis bins |
| `values_unit` | str | No | Unit for heatmap cell values |

## Signal Type Requirements

Both `x_expr` and `y_expr` must evaluate to `SampleSeries`. Virtual signals (Intervals, PointsInTime) cannot be used directly — convert them first using `.where()` or similar operations.

## Common Use Cases

### Engine Operating Map
```python
# Engine speed vs. torque — the classic powertrain map
Histogram2D(
    name="eng_map_p1",
    x_expr=signals["engine_speed"],
    y_expr=signals["engine_torque"],
    x_bins=[float(i) for i in range(0, 7000, 500)],
    y_bins=[float(i) for i in range(-50, 600, 50)],
    x_bins_unit="rpm",
    y_bins_unit="Nm"
)
```

### Driving Dynamics Profile
```python
# Vehicle speed vs. lateral acceleration
Histogram2D(
    name="dynamics_profile_p1",
    x_expr=signals["vehicle_speed"],
    y_expr=signals["lateral_acc"],
    x_bins=[float(i) for i in range(0, 220, 20)],
    y_bins=[round(i * 0.5, 1) for i in range(-20, 21)],
    x_bins_unit="km/h",
    y_bins_unit="m/s²"
)
```

### Thermal Loading Map
```python
# RPM vs. exhaust temperature
Histogram2D(
    name="thermal_map_p1",
    x_expr=signals["engine_speed"],
    y_expr=signals["exhaust_temp"],
    x_bins=[float(i) for i in range(0, 7000, 500)],
    y_bins=[float(i) for i in range(0, 1100, 100)],
    x_bins_unit="rpm",
    y_bins_unit="°C"
)
```

### EV Battery Usage Pattern
```python
# SOC vs. battery power
Histogram2D(
    name="battery_usage_p1",
    x_expr=signals["soc"],
    y_expr=signals["hv_batt_power"],
    x_bins=[float(i) for i in range(0, 110, 10)],
    y_bins=[float(i) for i in range(-300, 350, 50)],
    x_bins_unit="%",
    y_bins_unit="kW"
)
```

## Bin Selection Guidance

- Use physically meaningful ranges for both axes
- Fewer bins than 1D histograms (8-15 per axis is typical)
- Total cell count = x_bins * y_bins — keep under ~200 cells for readability
- Ensure both signals have overlapping measurement coverage

## Persistence Schema

2D histograms use a similar star schema to 1D histograms:

- `histogram_dimension` — Contains metadata, with separate `x_bins` and `y_bins` arrays
- `histogram_fact` — One row per (x_bin, y_bin, session) combination with `hist_value`

Query patterns are the same as 1D but with two bin dimensions. See `gold_layer_queries.md` for details.
