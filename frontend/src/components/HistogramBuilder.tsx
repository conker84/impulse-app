import { useState, useEffect } from "react";
import type { Histogram1DDefinition, SignalDefinition } from "../types";

type HistogramType = Histogram1DDefinition["histogram_type"];

interface BinSuggestion {
  bins: number[];
  bins_unit: string;
  description: string;
  name: string;
}

interface Props {
  signals: SignalDefinition[];
  existingNames: Set<string>;
  onAdd: (histogram: Histogram1DDefinition) => void;
  onSuggestBins: (type: string, signalRef: string) => Promise<BinSuggestion>;
  editingHistogram?: Histogram1DDefinition | null;
  onCancelEdit?: () => void;
}

const HISTOGRAM_TYPES: {
  key: HistogramType;
  label: string;
  description: string;
}[] = [
  {
    key: "duration",
    label: "Duration",
    description: "Time spent in each value range",
  },
  {
    key: "distance",
    label: "Distance",
    description: "Distance traveled in each value range",
  },
];

function makeUniqueName(
  base: string,
  existing: Set<string>
): string {
  if (!existing.has(base)) return base;
  for (let i = 2; i < 100; i++) {
    const candidate = `${base}_${i}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

export default function HistogramBuilder({
  signals,
  existingNames,
  onAdd,
  onSuggestBins,
  editingHistogram,
  onCancelEdit,
}: Props) {
  const [selectedType, setSelectedType] = useState<HistogramType | null>(null);
  const [signalRef, setSignalRef] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [binsText, setBinsText] = useState("");
  const [binsUnit, setBinsUnit] = useState("");
  const [maxDurationEnabled, setMaxDurationEnabled] = useState(false);
  const [maxDurationSec, setMaxDurationSec] = useState("");
  const [weightSignalRef, setWeightSignalRef] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState("");

  const isEditing = !!editingHistogram;

  useEffect(() => {
    if (editingHistogram) {
      setSelectedType(editingHistogram.histogram_type);
      setSignalRef(editingHistogram.signal_ref);
      setName(editingHistogram.name);
      setDescription(editingHistogram.description || "");
      setBinsText(editingHistogram.bins.join(", "));
      setBinsUnit(editingHistogram.bins_unit || "");
      if (editingHistogram.max_duration) {
        setMaxDurationEnabled(true);
        setMaxDurationSec(String(editingHistogram.max_duration / 1e9));
      } else {
        setMaxDurationEnabled(false);
        setMaxDurationSec("");
      }
      setWeightSignalRef(editingHistogram.weight_signal_ref || "");
    }
  }, [editingHistogram]);

  const resetForm = () => {
    setSignalRef("");
    setName("");
    setDescription("");
    setBinsText("");
    setBinsUnit("");
    setMaxDurationEnabled(false);
    setMaxDurationSec("");
    setWeightSignalRef("");
    setError("");
  };

  const handleTypeSelect = (type: HistogramType) => {
    if (selectedType === type) {
      setSelectedType(null);
      resetForm();
    } else {
      setSelectedType(type);
      resetForm();
    }
  };

  const handleSuggestBins = async () => {
    if (!selectedType || !signalRef) return;
    setSuggesting(true);
    setError("");
    try {
      const suggestion = await onSuggestBins(selectedType, signalRef);
      setBinsText(suggestion.bins.join(", "));
      if (suggestion.bins_unit) setBinsUnit(suggestion.bins_unit);
      if (suggestion.description) setDescription(suggestion.description);
      if (suggestion.name) {
        setName(makeUniqueName(suggestion.name, existingNames));
      }
    } catch (err) {
      setError(
        `Suggestion failed: ${err instanceof Error ? err.message : String(err)}`
      );
    } finally {
      setSuggesting(false);
    }
  };

  const parseBins = (): number[] | null => {
    const trimmed = binsText.trim();
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

  const handleAdd = () => {
    if (!selectedType || !signalRef) return;
    const bins = parseBins();
    if (!bins) {
      setError("Enter at least 2 valid, comma-separated bin edges.");
      return;
    }

    const finalName =
      name.trim() ||
      makeUniqueName(`${signalRef}_${selectedType}_p1`, existingNames);

    // In edit mode, allow keeping the same name
    if (!isEditing && existingNames.has(finalName)) {
      setError(`Name '${finalName}' already exists. Choose a different name.`);
      return;
    }

    const histogram: Histogram1DDefinition = {
      agg_kind: "histogram_1d",
      name: finalName,
      histogram_type: selectedType,
      signal_ref: signalRef,
      bins,
      bins_unit: binsUnit || null,
      values_unit: null,
      description,
      max_duration:
        selectedType === "duration" && maxDurationEnabled
          ? parseFloat(maxDurationSec) * 1e9 || null
          : null,
      event_signal_ref: null,
      weight_signal_ref:
        selectedType === "distance" && weightSignalRef
          ? weightSignalRef
          : null,
      weight_const: null,
    };

    onAdd(histogram);
    if (!isEditing) {
      setSelectedType(null);
      resetForm();
    } else if (onCancelEdit) {
      onCancelEdit();
      setSelectedType(null);
      resetForm();
    }
  };

  const canSuggest = !!selectedType && !!signalRef && !suggesting;
  const canAdd = !!selectedType && !!signalRef && !!parseBins();

  return (
    <div className="histogram-builder">
      <div className="histogram-builder-header">
        {isEditing ? "Edit Histogram" : "Add Histogram"}
        {isEditing && onCancelEdit && (
          <button
            className="action-btn"
            style={{ marginLeft: "auto", fontSize: 12, padding: "2px 8px" }}
            onClick={() => { onCancelEdit(); setSelectedType(null); resetForm(); }}
          >
            Cancel
          </button>
        )}
      </div>

      <div className="histogram-type-grid">
        {HISTOGRAM_TYPES.map((ht) => (
          <button
            key={ht.key}
            className={`histogram-type-card ${ht.key}${selectedType === ht.key ? " selected" : ""}`}
            onClick={() => handleTypeSelect(ht.key)}
          >
            <div className="histogram-type-card-label">{ht.label}</div>
            <div className="histogram-type-card-desc">{ht.description}</div>
          </button>
        ))}
      </div>

      {selectedType && (
        <div className="histogram-builder-form">
          <div className="form-group">
            <label className="form-label">
              Signal <span style={{ color: "var(--error)" }}>*</span>
            </label>
            <select
              className="form-input"
              value={signalRef}
              onChange={(e) => {
                setSignalRef(e.target.value);
                setBinsText("");
                setBinsUnit("");
                setDescription("");
                setName("");
              }}
            >
              <option value="">Select a signal...</option>
              {signals.map((s) => (
                <option key={s.var_name} value={s.var_name}>
                  {s.var_name}
                  {s.description ? ` — ${s.description}` : ""}
                </option>
              ))}
            </select>
          </div>

          <button
            className="action-btn autofill-btn"
            disabled={!canSuggest}
            onClick={handleSuggestBins}
          >
            {suggesting ? (
              <>
                <span className="spinner" /> Auto-filling...
              </>
            ) : (
              "Auto-fill"
            )}
          </button>


          {selectedType === "distance" && (
            <div className="form-group">
              <label className="form-label">
                Weight / Distance Signal{" "}
                <span style={{ color: "var(--error)" }}>*</span>
              </label>
              <select
                className="form-input"
                value={weightSignalRef}
                onChange={(e) => setWeightSignalRef(e.target.value)}
              >
                <option value="">Select distance signal...</option>
                {signals.map((s) => (
                  <option key={s.var_name} value={s.var_name}>
                    {s.var_name}
                    {s.description ? ` — ${s.description}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="form-group">
            <label className="form-label">
              Bins <span style={{ color: "var(--error)" }}>*</span>
            </label>
            <textarea
              className="form-input histogram-bins-input"
              value={binsText}
              onChange={(e) => setBinsText(e.target.value)}
              placeholder="0, 500, 1000, 1500, 2000, ..."
              rows={2}
            />
            <div className="form-hint">
              Comma-separated bin edges (at least 2). N edges create N-1 bins.
            </div>
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Bins Unit</label>
              <input
                className="form-input"
                value={binsUnit}
                onChange={(e) => setBinsUnit(e.target.value)}
                placeholder='e.g. "rpm", "°C", "km/h"'
              />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Name</label>
              <input
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={
                  signalRef
                    ? `${signalRef}_${selectedType}_p1`
                    : "auto-generated"
                }
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <input
              className="form-input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short description of this histogram"
            />
          </div>

          {selectedType === "duration" && (
            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={maxDurationEnabled}
                  onChange={(e) => {
                    setMaxDurationEnabled(e.target.checked);
                    if (!e.target.checked) setMaxDurationSec("");
                  }}
                />
                Limit max sample duration
              </label>
              {maxDurationEnabled && (
                <>
                  <input
                    className="form-input"
                    type="number"
                    min="1"
                    step="1"
                    value={maxDurationSec}
                    onChange={(e) => setMaxDurationSec(e.target.value)}
                    placeholder="e.g. 100"
                    style={{ marginTop: 6 }}
                  />
                  <div className="form-hint">
                    Duration in seconds. Caps individual samples to avoid outlier inflation.
                  </div>
                </>
              )}
            </div>
          )}

          {error && (
            <div
              style={{
                color: "var(--error)",
                fontSize: 12,
                marginBottom: 8,
              }}
            >
              {error}
            </div>
          )}

          <button
            className="action-btn primary"
            style={{ width: "100%" }}
            disabled={!canAdd}
            onClick={handleAdd}
          >
            {isEditing ? "Save Changes" : "Add Histogram"}
          </button>
        </div>
      )}
    </div>
  );
}
