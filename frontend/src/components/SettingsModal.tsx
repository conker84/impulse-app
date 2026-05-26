import { useState, useEffect, useCallback } from "react";
import { getUserStatus, saveClusterSetting, saveModelSetting } from "../api";
import type { UserStatusResponse } from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: Props) {
  const [status, setStatus] = useState<UserStatusResponse | null>(null);
  const [clusterId, setClusterId] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [savingCluster, setSavingCluster] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await getUserStatus();
      setStatus(s);
    } catch {
      setError("Failed to load settings");
    }
  }, []);

  useEffect(() => {
    if (open) {
      refresh().then(() => {});
      setError("");
      setSuccess("");
    }
  }, [open, refresh]);

  useEffect(() => {
    if (status) {
      setClusterId(status.cluster_id || "");
      setSelectedModel(status.serving_endpoint || "");
    }
  }, [status]);

  if (!open) return null;

  const handleSaveCluster = async () => {
    setError("");
    setSuccess("");
    setSavingCluster(true);
    try {
      await saveClusterSetting(clusterId.trim());
      setSuccess("Cluster configuration saved.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save cluster config");
    } finally {
      setSavingCluster(false);
    }
  };

  const handleSaveModel = async () => {
    setError("");
    setSuccess("");
    setSavingModel(true);
    try {
      await saveModelSetting(selectedModel);
      setSuccess("Model preference saved.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save model preference");
    } finally {
      setSavingModel(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">Settings</div>
          <button className="modal-close" onClick={onClose}>
            &times;
          </button>
        </div>

        <div className="modal-body">
          <div className="settings-info">
            Choose which AI model powers the assistant. Larger models reason
            better but cost more per turn.
          </div>

          <div className="settings-field">
            <label htmlFor="model-select">AI Model</label>
            <select
              id="model-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="settings-input"
            >
              {(status?.available_models || []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {!status?.local_mode && (
            <div className="settings-actions">
              <button
                className="btn btn-primary"
                onClick={handleSaveModel}
                disabled={savingModel || selectedModel === (status?.serving_endpoint || "")}
              >
                {savingModel ? "Saving..." : "Save Model"}
              </button>
            </div>
          )}

          {error && <div className="settings-error">{error}</div>}
          {success && <div className="settings-success">{success}</div>}

          {!status?.local_mode && (
            <>
              <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "20px 0" }} />

              <div className="settings-info">
                Optionally configure an all-purpose cluster for the
                report orchestration task. Leave empty to use serverless compute.
              </div>

              <div className="settings-field">
                <label htmlFor="cluster-input">All-Purpose Cluster ID</label>
                <input
                  id="cluster-input"
                  type="text"
                  placeholder="e.g. 0123-456789-abcdefgh"
                  value={clusterId}
                  onChange={(e) => setClusterId(e.target.value)}
                  className="settings-input"
                />
              </div>

              <div className="settings-actions">
                <button
                  className="btn btn-primary"
                  onClick={handleSaveCluster}
                  disabled={savingCluster || clusterId === (status?.cluster_id || "")}
                >
                  {savingCluster ? "Saving..." : "Save Cluster Config"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
