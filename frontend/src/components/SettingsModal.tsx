import { useState, useEffect, useCallback } from "react";
import { getTokenStatus, saveToken, deleteToken, saveClusterSetting } from "../api";
import type { TokenStatusResponse } from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SettingsModal({ open, onClose }: Props) {
  const [status, setStatus] = useState<TokenStatusResponse | null>(null);
  const [pat, setPat] = useState("");
  const [clusterId, setClusterId] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingCluster, setSavingCluster] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await getTokenStatus();
      setStatus(s);
    } catch {
      setError("Failed to check token status");
    }
  }, []);

  useEffect(() => {
    if (open) {
      refresh().then(() => {});
      setPat("");
      setError("");
      setSuccess("");
    }
  }, [open, refresh]);

  useEffect(() => {
    if (status) {
      setClusterId(status.cluster_id || "");
    }
  }, [status]);

  if (!open) return null;

  const handleSave = async () => {
    setError("");
    setSuccess("");
    if (!pat.trim()) {
      setError("Please enter your Personal Access Token.");
      return;
    }
    setSaving(true);
    try {
      await saveToken(pat.trim());
      setSuccess("Token saved successfully.");
      setPat("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save token");
    } finally {
      setSaving(false);
    }
  };

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

  const handleDelete = async () => {
    setError("");
    setSuccess("");
    setDeleting(true);
    try {
      await deleteToken();
      setSuccess("Token deleted.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete token");
    } finally {
      setDeleting(false);
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
          {status?.local_mode ? (
            <div className="settings-info">
              Running in local mode. Authentication uses your local Databricks
              profile &mdash; no PAT needed.
            </div>
          ) : (
            <>
              <div className="settings-info">
                A Databricks Personal Access Token (PAT) is required to deploy
                &amp; run reports as Databricks jobs.
              </div>

              <div className="token-status">
                <span
                  className={`status-dot ${status?.has_token ? "status-ok" : "status-missing"}`}
                />
                {status?.has_token
                  ? `Token configured for ${status.user_email || "you"}`
                  : "No token configured"}
              </div>

              <div className="settings-field">
                <label htmlFor="pat-input">Personal Access Token</label>
                <input
                  id="pat-input"
                  type="password"
                  placeholder="dapi..."
                  value={pat}
                  onChange={(e) => setPat(e.target.value)}
                  className="settings-input"
                />
              </div>

              {error && <div className="settings-error">{error}</div>}
              {success && <div className="settings-success">{success}</div>}

              <div className="settings-actions">
                <button
                  className="btn btn-primary"
                  onClick={handleSave}
                  disabled={saving || !pat.trim()}
                >
                  {saving ? "Saving..." : "Save Token"}
                </button>
                {status?.has_token && (
                  <button
                    className="btn btn-danger"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? "Deleting..." : "Delete Token"}
                  </button>
                )}
              </div>

              <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "20px 0" }} />

              <div className="settings-info">
                Optionally configure an all-purpose cluster for the
                report orchestration task. Leave empty to use a job cluster.
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
