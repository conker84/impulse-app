# Define Channels

Define physical and virtual channels for an Impulse framework report.

## Overview

This skill helps users define time series channels in a report's `01_signal_definitions.py` file. It covers physical signal extraction from the measurement database and virtual signal creation through expressions (arithmetic, filtering, event detection, aggregation, and calculus). The skill understands the Impulse query engine's core data model (SampleSeries, Intervals, PointsInTime, PitSeries) and guides users through building signal chains.

## What's Included

```
define-signals/
├── SKILL.md                             # Signal definition workflow and expression guide
├── README.md                            # This file
└── references/
    ├── sample_series_api.md             # SampleSeries methods (filtering, aggregation, calculus)
    ├── intervals_api.md                 # Intervals methods (expand, shrink, filter, merge)
    ├── points_in_time_api.md            # PointsInTime methods (expand, flipflop, filter)
    └── pit_series_api.md               # PitSeries methods (histogram, min, max)
```

## Key Topics

- Physical signal extraction via `query.channel()` (using channel tag key-value pairs)
- Virtual signal creation through arithmetic, comparison, and logical operations
- Event detection (rising/falling edges, state change points)
- Interval creation (flipflop, expand from points)
- Signal filtering with `.where()` (by intervals or points in time)
- Aggregation within intervals (max, min, mean)
- Resampling and calculus (resample, cumtrapz, diff, trapz)
- Core data model type flow (SampleSeries → Intervals → PointsInTime → PitSeries)

## When to Use

- After scaffolding and configuring a new report, to define the signals for analysis
- When adding new visualizations that require additional signals
- When modifying signal transformations (filtering, masking, derived metrics)
- User invokes `/define-signals` with an optional report name

## Related Skills

- [create-report](../create-report/) — scaffold a new report
- [configure-report](../configure-report/) — configure report data sources and vehicles

## Resources

For detailed API documentation, refer to the Impulse framework query engine docs (available locally):

- `<impulse_framework_path>/impulse_query_engine/docs/signal_definition.md` — signal definition overview
- `<impulse_framework_path>/impulse_query_engine/docs/api/model/` — full API docs for all data model classes
