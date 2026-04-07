import { useState } from "react";
import type { EventDefinition, Histogram2DDefinition, SignalDefinition } from "../types";

interface Props {
  signals: SignalDefinition[];
  events: EventDefinition[];
  existingNames: Set<string>;
  onAdd: (histogram: Histogram2DDefinition) => void;
  onSuggestBins: (type: string, signalRef: string) => Promise<{
    bins: number[]; bins_unit: string; description: string; name: string;
  }>;
}

function makeUniqueName(base: string, existing: Set<string>): string {
  if (!existing.has(base)) return base;
  for (let i = 2; i < 100; i++) {
    const candidate = `${base}_${i}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

export default function Histogram2DBuilder({ signals, events, existingNames, onAdd, onSuggestBins }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [xSignalRef, setXSignalRef] = useState("");
  const [ySignalRef, setYSignalRef] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [xBinsText, setXBinsText] = useState("");
  const [yBinsText, setYBinsText] = useState("");
  const [xBinsUnit, setXBinsUnit] = useState("");
  const [yBinsUnit, setYBinsUnit] = useState("");
  const [eventRef, setEventRef] = useState("");
  const [suggesting, setSuggesting] = useState<"x" | "y" | null>(null);
  const [error, setError] = useState("");

  const resetForm = () => {
    setXSignalRef("");
    setYSignalRef("");
    setName("");
    setDescription("");
    setXBinsText("");
    setYBinsText("");
    setXBinsUnit("");
    setYBinsUnit("");
    setEventRef("");
    setError("");
  };

  const parseBins = (text: string): number[] | null => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    const parts = trimmed.split(/[\s,]+/).filter(Boolean);
    const nums: number[] = [];
    for (const p of parts) {
      const n = parseFloat(p);
      if (isNaN(n)) return null;
      nums.push(n);
    }
    return nums.length >= 2 ? nums : null;
  };

  const handleAutoFill = async (axis: "x" | "y") => {
    const ref = axis === "x" ? xSignalRef : ySignalRef;
    if (!ref) return;
    setSuggesting(axis);
    setError("");
    try {
      const suggestion = await onSuggestBins("duration", ref);
      if (axis === "x") {
        setXBinsText(suggestion.bins.join(", "));
        if (suggestion.bins_unit) setXBinsUnit(suggestion.bins_unit);
      } else {
        setYBinsText(suggestion.bins.join(", "));
        if (suggestion.bins_unit) setYBinsUnit(suggestion.bins_unit);
      }
      // Auto-fill name and description from first suggestion only
      if (!name && !description && suggestion.description) {
        setDescription(suggestion.description);
      }
    } catch (err) {
      setError(`Auto-fill failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSuggesting(null);
    }
  };

  const handleAutoFillBoth = async () => {
    if (!xSignalRef || !ySignalRef) return;
    setSuggesting("x");
    setError("");
    try {
      const [xSugg, ySugg] = await Promise.all([
        onSuggestBins("duration", xSignalRef),
        onSuggestBins("duration", ySignalRef),
      ]);
      setXBinsText(xSugg.bins.join(", "));
      if (xSugg.bins_unit) setXBinsUnit(xSugg.bins_unit);
      setYBinsText(ySugg.bins.join(", "));
      if (ySugg.bins_unit) setYBinsUnit(ySugg.bins_unit);
    } catch (err) {
      setError(`Auto-fill failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSuggesting(null);
    }
  };

  const handleAdd = () => {
    if (!xSignalRef || !ySignalRef) return;
    const xBins = parseBins(xBinsText);
    const yBins = parseBins(yBinsText);
    if (!xBins) {
      setError("Enter at least 2 valid X bin edges.");
      return;
    }
    if (!yBins) {
      setError("Enter at least 2 valid Y bin edges.");
      return;
    }

    const finalName =
      name.trim() ||
      makeUniqueName(`${xSignalRef}_${ySignalRef}_2d_p1`, existingNames);

    if (existingNames.has(finalName)) {
      setError(`Name '${finalName}' already exists.`);
      return;
    }

    const histogram: Histogram2DDefinition = {
      agg_kind: "histogram_2d",
      name: finalName,
      x_signal_ref: xSignalRef,
      y_signal_ref: ySignalRef,
      x_bins: xBins,
      y_bins: yBins,
      x_bins_unit: xBinsUnit || null,
      y_bins_unit: yBinsUnit || null,
      x_signal_name: null,
      y_signal_name: null,
      values_unit: null,
      event_ref: eventRef || null,
      description,
    };

    onAdd(histogram);
    setExpanded(false);
    resetForm();
  };

  const canAdd =
    !!xSignalRef && !!ySignalRef && !!parseBins(xBinsText) && !!parseBins(yBinsText);
  const canAutoFill = !!xSignalRef && !!ySignalRef && !suggesting;

  if (!expanded) {
    return (
      <button
        className="action-btn"
        style={{ width: "100%", marginTop: 8 }}
        onClick={() => setExpanded(true)}
      >
        + Add 2D Histogram
      </button>
    );
  }

  return (
    <div className="histogram-builder" style={{ marginTop: 8 }}>
      <div className="histogram-builder-header">
        Add 2D Histogram
        <button
          className="action-btn"
          style={{ marginLeft: "auto", fontSize: 12, padding: "2px 8px" }}
          onClick={() => { setExpanded(false); resetForm(); }}
        >
          Cancel
        </button>
      </div>

      <div className="histogram-builder-form">
        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">
              X Signal <span style={{ color: "var(--error)" }}>*</span>
            </label>
            <select
              className="form-input"
              value={xSignalRef}
              onChange={(e) => { setXSignalRef(e.target.value); setXBinsText(""); setXBinsUnit(""); }}
            >
              <option value="">Select X signal...</option>
              {signals.map((s) => (
                <option key={s.var_name} value={s.var_name}>
                  {s.var_name}{s.description ? ` — ${s.description}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">
              Y Signal <span style={{ color: "var(--error)" }}>*</span>
            </label>
            <select
              className="form-input"
              value={ySignalRef}
              onChange={(e) => { setYSignalRef(e.target.value); setYBinsText(""); setYBinsUnit(""); }}
            >
              <option value="">Select Y signal...</option>
              {signals.map((s) => (
                <option key={s.var_name} value={s.var_name}>
                  {s.var_name}{s.description ? ` — ${s.description}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          className="action-btn autofill-btn"
          disabled={!canAutoFill}
          onClick={handleAutoFillBoth}
        >
          {suggesting ? (
            <>
              <span className="spinner" /> Auto-filling...
            </>
          ) : (
            "Auto-fill both axes"
          )}
        </button>

        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">
              X Bins <span style={{ color: "var(--error)" }}>*</span>
              {xSignalRef && (
                <button
                  className="action-btn"
                  style={{ marginLeft: 8, fontSize: 10, padding: "1px 6px" }}
                  disabled={!xSignalRef || suggesting === "x"}
                  onClick={() => handleAutoFill("x")}
                >
                  {suggesting === "x" ? "..." : "auto-fill"}
                </button>
              )}
            </label>
            <textarea
              className="form-input histogram-bins-input"
              value={xBinsText}
              onChange={(e) => setXBinsText(e.target.value)}
              placeholder="0, 1000, 2000, 3000, ..."
              rows={2}
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">
              Y Bins <span style={{ color: "var(--error)" }}>*</span>
              {ySignalRef && (
                <button
                  className="action-btn"
                  style={{ marginLeft: 8, fontSize: 10, padding: "1px 6px" }}
                  disabled={!ySignalRef || suggesting === "y"}
                  onClick={() => handleAutoFill("y")}
                >
                  {suggesting === "y" ? "..." : "auto-fill"}
                </button>
              )}
            </label>
            <textarea
              className="form-input histogram-bins-input"
              value={yBinsText}
              onChange={(e) => setYBinsText(e.target.value)}
              placeholder="0, 50, 100, 150, ..."
              rows={2}
            />
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">X Unit</label>
            <input
              className="form-input"
              value={xBinsUnit}
              onChange={(e) => setXBinsUnit(e.target.value)}
              placeholder='e.g. "rpm"'
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Y Unit</label>
            <input
              className="form-input"
              value={yBinsUnit}
              onChange={(e) => setYBinsUnit(e.target.value)}
              placeholder='e.g. "Nm"'
            />
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Name</label>
            <input
              className="form-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={
                xSignalRef && ySignalRef
                  ? `${xSignalRef}_${ySignalRef}_2d_p1`
                  : "auto-generated"
              }
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

        <div className="form-group">
          <label className="form-label">Event Filter (optional)</label>
          <select
            className="form-input"
            value={eventRef}
            onChange={(e) => setEventRef(e.target.value)}
          >
            <option value="">None — no event filter</option>
            {events.filter((e) => e.event_type === "interval").map((e) => (
              <option key={e.name} value={e.name}>
                {e.name}{e.description ? ` — ${e.description}` : ""}
              </option>
            ))}
          </select>
          <div className="form-hint">
            Only interval events are compatible with histograms. Define events in the Channels tab.
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
          disabled={!canAdd}
          onClick={handleAdd}
        >
          Add 2D Histogram
        </button>
      </div>
    </div>
  );
}
