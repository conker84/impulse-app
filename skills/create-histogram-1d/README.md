# Create 1D Histogram

Add 1D histogram visualizations to an Impulse framework report.

## Overview

This skill guides the user through creating 1D histogram visualizations. It covers four histogram types — Duration, Distance, Duration Count, and Event Count — and handles parameter collection, bin definition, expression type verification, and integration into report pages.

## What's Included

```
create-histogram-1d/
├── SKILL.md                         # Workflow, type selection, parameter collection, code patterns
├── README.md                        # This file
└── references/
    └── histogram_types.md           # Detailed constructor params, examples, persistence schema
```

## Key Topics

- Four 1D histogram types and when to use each
- Constructor parameters per type
- Bin definition patterns (equidistant, numpy, catch-all, custom)
- Expression type requirements and verification
- Integration into report pages (`page.add_aggregation()`)
- Persistence schema (histogram_dimension + histogram_fact)

## When to Use

- Adding histogram visualizations to a report page
- User asks to "create a histogram", "add a distribution chart", or "analyze signal distribution"
- User invokes `/create-histogram-1d` with an optional report name

## Related Skills

- [define-channels](../define-channels/) — define the signals referenced by histograms
- [configure-report](../configure-report/) — configure data sources before running the report
- [create-report](../create-report/) — scaffold a new report

## Resources

For detailed documentation, refer to the Impulse framework reporting docs (available locally):

- `<impulse_framework_path>/mda_reporting/docs/visualizations/histogram1d.md` — 1D histogram documentation
- `<impulse_framework_path>/mda_reporting/docs/er_diagrams/histogramNd_er_diagram.md` — persistence ER diagram
