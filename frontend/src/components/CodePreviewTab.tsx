import type { Histogram1DDefinition, ReportState } from "../types";

interface Props {
  state: ReportState;
}

function generateSignalCode(state: ReportState): string {
  const lines: string[] = [
    "# Databricks notebook source",
    "# MAGIC %md",
    "# MAGIC ##### Signal Definitions",
    "",
    "# COMMAND ----------",
    "",
  ];

  const physical = state.signals.filter((s) => s.signal_type === "physical");
  const virtual = state.signals.filter((s) => s.signal_type === "virtual");

  if (physical.length > 0) {
    lines.push("# Physical channels");
    physical.forEach((s) => {
      const chName = s.channel_name || s.alias || s.var_name;
      lines.push(`${s.var_name} = query.channel(channel_name="${chName}")`);
    });
    lines.push("", "# COMMAND ----------", "");
  }

  if (virtual.length > 0) {
    lines.push("# Virtual / derived signals");
    virtual.forEach((s) => {
      lines.push(`${s.var_name} = ${s.expression}`);
    });
    lines.push("", "# COMMAND ----------", "");
  }

  lines.push("signals = {");
  state.signals.forEach((s) => {
    lines.push(`    "${s.var_name}": ${s.var_name},`);
  });
  lines.push("}", "", "globals().update(locals())");

  return lines.join("\n");
}

function generateHistogramCode(state: ReportState): string {
  const histograms = state.aggregations.filter(
    (a): a is Histogram1DDefinition => a.agg_kind === "histogram_1d"
  );
  if (histograms.length === 0) return "# No histograms defined yet";

  const lines: string[] = [
    "my_first_page = Page(page_number=1)",
    "my_report.add_page(my_first_page)",
    "",
  ];

  histograms.forEach((h) => {
    const params = [`    name="${h.name}"`, `    base_expr=signals["${h.signal_ref}"]`, `    bins=${JSON.stringify(h.bins)}`];
    if (h.event_signal_ref) params.push(`    event=BasicEvent(name="${h.name}_event", expr=signals["${h.event_signal_ref}"])`);
    if (h.description) params.push(`    desc="${h.description}"`);
    params.push(`    agg_type="${h.histogram_type}"`);
    if (h.bins_unit) params.push(`    bins_unit="${h.bins_unit}"`);

    lines.push(`hist = Histogram(`, params.join(",\n") + ",", ")");
    lines.push("my_first_page.add_aggregation(hist)", "");
  });

  return lines.join("\n");
}

export default function CodePreviewTab({ state }: Props) {
  const hasHistograms = state.aggregations.some((a) => a.agg_kind === "histogram_1d");

  if (state.signals.length === 0 && state.aggregations.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#x1F4DD;</div>
        <div>No code to preview yet</div>
        <div style={{ fontSize: 12 }}>
          Define signals and aggregations to see the generated code.
        </div>
      </div>
    );
  }

  return (
    <div>
      {state.signals.length > 0 && (
        <>
          <div className="code-label">01_signal_definitions.py</div>
          <div className="code-block">{generateSignalCode(state)}</div>
        </>
      )}

      {hasHistograms && (
        <>
          <div className="code-label">01_histograms.py</div>
          <div className="code-block">{generateHistogramCode(state)}</div>
        </>
      )}
    </div>
  );
}
