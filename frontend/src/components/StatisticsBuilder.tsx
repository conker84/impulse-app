import { useEffect, useState } from "react";
import type { EventDefinition, SignalDefinition, StatisticsDefinition } from "../types";

interface Props {
  signals: SignalDefinition[];
  events: EventDefinition[];
  existingNames: Set<string>;
  onAdd: (stats: StatisticsDefinition) => void;
  editingStatistics?: StatisticsDefinition | null;
  onCancelEdit?: () => void;
}

const ALL_STAT_LABELS = ["min", "max", "mean", "median"] as const;

function makeUniqueName(base: string, existing: Set<string>): string {
  if (!existing.has(base)) return base;
  for (let i = 2; i < 100; i++) {
    const candidate = `${base}_${i}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

export default function StatisticsBuilder({ signals, events, existingNames, onAdd, editingStatistics, onCancelEdit }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [selectedSignals, setSelectedSignals] = useState<Set<string>>(new Set());
  const [selectedStats, setSelectedStats] = useState<Set<string>>(new Set(ALL_STAT_LABELS));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [eventRef, setEventRef] = useState("");
  const [error, setError] = useState("");

  const isEditing = !!editingStatistics;

  const resetForm = () => {
    setSelectedSignals(new Set());
    setSelectedStats(new Set(ALL_STAT_LABELS));
    setName("");
    setDescription("");
    setEventRef("");
    setError("");
  };

  useEffect(() => {
    if (editingStatistics) {
      setExpanded(true);
      setSelectedSignals(new Set(editingStatistics.signal_refs));
      setSelectedStats(new Set(editingStatistics.stat_labels));
      setName(editingStatistics.name);
      setDescription(editingStatistics.description || "");
      setEventRef(editingStatistics.event_ref || "");
      setError("");
    }
  }, [editingStatistics]);

  const toggleSignal = (varName: string) => {
    setSelectedSignals((prev) => {
      const next = new Set(prev);
      if (next.has(varName)) next.delete(varName);
      else next.add(varName);
      return next;
    });
  };

  const toggleStat = (label: string) => {
    setSelectedStats((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const handleAdd = () => {
    if (selectedSignals.size === 0) {
      setError("Select at least one signal.");
      return;
    }
    if (selectedStats.size === 0) {
      setError("Select at least one statistic.");
      return;
    }

    const signalRefs = Array.from(selectedSignals);
    const finalName =
      name.trim() ||
      makeUniqueName(
        signalRefs.length === 1
          ? `${signalRefs[0]}_stats_p1`
          : `multi_stats_p1`,
        existingNames
      );

    if (!isEditing && existingNames.has(finalName)) {
      setError(`Name '${finalName}' already exists.`);
      return;
    }

    const stats: StatisticsDefinition = {
      agg_kind: "statistics",
      name: finalName,
      signal_refs: signalRefs,
      stat_labels: Array.from(selectedStats),
      event_ref: eventRef || null,
      signal_names: null,
      description,
    };

    onAdd(stats);
    if (!isEditing) {
      setExpanded(false);
      resetForm();
    } else if (onCancelEdit) {
      onCancelEdit();
      setExpanded(false);
      resetForm();
    }
  };

  if (!expanded) {
    return (
      <button
        className="action-btn"
        style={{ width: "100%", marginTop: 8 }}
        onClick={() => setExpanded(true)}
      >
        + Add Statistics
      </button>
    );
  }

  return (
    <div className="histogram-builder" style={{ marginTop: 8 }}>
      <div className="histogram-builder-header">
        {isEditing ? "Edit Statistics" : "Add Statistics"}
        <button
          className="action-btn"
          style={{ marginLeft: "auto", fontSize: 12, padding: "2px 8px" }}
          onClick={() => {
            if (isEditing && onCancelEdit) onCancelEdit();
            setExpanded(false);
            resetForm();
          }}
        >
          Cancel
        </button>
      </div>

      <div className="histogram-builder-form">
        <div className="form-group">
          <label className="form-label">
            Signals <span style={{ color: "var(--error)" }}>*</span>
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {signals.map((s) => (
              <label
                key={s.var_name}
                className="checkbox-label"
                style={{
                  fontSize: 12,
                  padding: "3px 8px",
                  borderRadius: 4,
                  border: "1px solid var(--border)",
                  background: selectedSignals.has(s.var_name) ? "var(--accent-bg, rgba(59, 130, 246, 0.1))" : "transparent",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedSignals.has(s.var_name)}
                  onChange={() => toggleSignal(s.var_name)}
                  style={{ marginRight: 4 }}
                />
                {s.var_name}
              </label>
            ))}
          </div>
          <div className="form-hint">
            {selectedSignals.size} signal(s) selected
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">
            Statistics <span style={{ color: "var(--error)" }}>*</span>
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {ALL_STAT_LABELS.map((label) => (
              <label
                key={label}
                className="checkbox-label"
                style={{
                  fontSize: 12,
                  padding: "3px 8px",
                  borderRadius: 4,
                  border: "1px solid var(--border)",
                  background: selectedStats.has(label) ? "var(--accent-bg, rgba(59, 130, 246, 0.1))" : "transparent",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={selectedStats.has(label)}
                  onChange={() => toggleStat(label)}
                  style={{ marginRight: 4 }}
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Event Filter (optional)</label>
          <select
            className="form-input"
            value={eventRef}
            onChange={(e) => setEventRef(e.target.value)}
          >
            <option value="">None — compute over full signal</option>
            {events.filter((e) => e.event_type === "interval" || e.event_type === "periodic_distance").map((e) => (
              <option key={e.name} value={e.name}>
                {e.name}{e.description ? ` — ${e.description}` : ""}
              </option>
            ))}
          </select>
          <div className="form-hint">
            Only interval events are compatible. Define events in the Channels tab.
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Name</label>
            <input
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="auto-generated"
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Description</label>
            <input
              className="form-input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short description"
            />
          </div>
        </div>

        {error && (
          <div style={{ color: "var(--error)", fontSize: 12, marginBottom: 8 }}>
            {error}
          </div>
        )}

        <button
          className="action-btn primary"
          style={{ width: "100%" }}
          disabled={selectedSignals.size === 0 || selectedStats.size === 0}
          onClick={handleAdd}
        >
          {isEditing ? "Save Changes" : "Add Statistics"}
        </button>
      </div>
    </div>
  );
}
