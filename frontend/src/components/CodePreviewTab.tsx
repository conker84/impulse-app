import type { ReportState } from "../types";

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
      lines.push(`${s.var_name} = query.channel_with_alias(ChannelAliasName_withScope="${s.alias}")`);
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
  if (state.histograms.length === 0) return "# No histograms defined yet";

  const classMap: Record<string, string> = {
    duration: "HistogramDuration",
    distance: "HistogramDistance",
    duration_count: "HistogramDurationCount",
    event_count: "HistogramEventCount",
  };

  const lines: string[] = [
    "my_first_page = Page(page_number=1)",
    "my_first_chapter.add_page(my_first_page)",
    "",
  ];

  state.histograms.forEach((h) => {
    const cls = classMap[h.histogram_type];
    const params = [`    name="${h.name}"`, `    base_expr=signals["${h.signal_ref}"]`, `    bins=${JSON.stringify(h.bins)}`];
    if (h.histogram_type === "duration" && h.max_duration) params.push(`    max_duration=${h.max_duration}`);
    if (h.event_signal_ref) params.push(`    event_expr=signals["${h.event_signal_ref}"]`);
    if (h.bins_unit) params.push(`    bins_unit="${h.bins_unit}"`);
    if (h.description) params.push(`    desc="${h.description}"`);

    lines.push(`hist = ${cls}(`, params.join(",\n") + ",", ")");
    lines.push("my_first_page.add_visualization(hist)", "");
  });

  return lines.join("\n");
}

export default function CodePreviewTab({ state }: Props) {
  if (state.signals.length === 0 && state.histograms.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#x1F4DD;</div>
        <div>No code to preview yet</div>
        <div style={{ fontSize: 12 }}>
          Define signals and histograms to see the generated code.
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

      {state.histograms.length > 0 && (
        <>
          <div className="code-label">01_histograms.py</div>
          <div className="code-block">{generateHistogramCode(state)}</div>
        </>
      )}
    </div>
  );
}
