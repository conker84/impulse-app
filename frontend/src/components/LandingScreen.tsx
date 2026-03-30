import { useState, useEffect } from "react";
import type { SavedReportSummary } from "../types";
import { listSavedReports, deleteReport } from "../api";

interface Props {
  onNewReport: () => void;
  onLoadReport: (reportId: string) => void;
  onVisualize: (reportId: string) => void;
  onTimeSeries?: () => void;
  settingsButton?: React.ReactNode;
}

function ReportIcon({ size = 48 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="4" width="40" height="40" rx="6" fill="var(--accent-bg)" stroke="var(--accent)" strokeWidth="1.5" />
      <rect x="11" y="28" width="6" height="10" rx="1.5" fill="var(--accent)" opacity="0.5" />
      <rect x="21" y="20" width="6" height="18" rx="1.5" fill="var(--accent)" opacity="0.7" />
      <rect x="31" y="12" width="6" height="26" rx="1.5" fill="var(--accent)" />
      <line x1="9" y1="40" x2="39" y2="40" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" opacity="0.4" />
    </svg>
  );
}

function CardReportIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="3" y="3" width="26" height="26" rx="4" fill="var(--accent-bg)" />
      <rect x="8" y="18" width="4" height="7" rx="1" fill="var(--accent)" opacity="0.5" />
      <rect x="14" y="13" width="4" height="12" rx="1" fill="var(--accent)" opacity="0.7" />
      <rect x="20" y="8" width="4" height="17" rx="1" fill="var(--accent)" />
    </svg>
  );
}

export default function LandingScreen({ onNewReport, onLoadReport, onVisualize, onTimeSeries, settingsButton }: Props) {
  const [reports, setReports] = useState<SavedReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);

  const fetchReports = () => {
    setLoading(true);
    listSavedReports()
      .then((res) => setReports(res.reports))
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchReports();
  }, []);

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete report "${name}"? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      await deleteReport(id);
      setReports((prev) => prev.filter((r) => r.id !== id));
    } catch {
      // silently ignore
    } finally {
      setDeleting(null);
    }
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  return (
    <div className="landing-screen">
      {settingsButton && <div className="landing-settings-corner">{settingsButton}</div>}
      <div className="landing-container">
        <div className="landing-hero">
          <div className="landing-icon">
            <ReportIcon size={56} />
          </div>
          <h1 className="landing-title">Impulse</h1>
          <p className="landing-subtitle">
            Create and manage measurement data reports using a guided wizard.
            <br />
            Describe your analysis in plain language and deploy to Databricks.
          </p>
        </div>

        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <button className="landing-new-btn" onClick={onNewReport}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" style={{ marginRight: 8, verticalAlign: -3 }}>
              <path d="M9 2v14M2 9h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
            </svg>
            Create New Report
          </button>
          {onTimeSeries && (
            <button className="landing-new-btn landing-ts-btn" onClick={onTimeSeries}>
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" style={{ marginRight: 8, verticalAlign: -3 }}>
                <polyline points="2,14 6,8 10,11 14,4 17,6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              Explore Time Series
            </button>
          )}
        </div>

        {loading && (
          <div className="landing-loading">
            <span className="spinner" style={{ marginRight: 8 }} />
            Loading saved reports...
          </div>
        )}

        {!loading && reports.length > 0 && (
          <div className="landing-reports-section">
            <h2 className="landing-section-title">Saved Reports</h2>
            <div className="landing-reports-list">
              {reports.map((r) => (
                <div key={r.id} className="landing-report-card" onClick={() => onLoadReport(r.id)}>
                  <div className="landing-report-icon">
                    <CardReportIcon />
                  </div>
                  <div className="landing-report-info">
                    <div className="landing-report-name">{r.report_name}</div>
                    {r.description && (
                      <div className="landing-report-desc">{r.description}</div>
                    )}
                    <div className="landing-report-meta">
                      {r.creator && <span>{r.creator}</span>}
                      {r.updated_at && <span>{formatDate(r.updated_at)}</span>}
                    </div>
                  </div>
                  <div className="landing-report-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="landing-report-open"
                      onClick={() => onLoadReport(r.id)}
                    >
                      Open
                    </button>
                    <button
                      className="landing-report-visualize"
                      onClick={() => onVisualize(r.id)}
                    >
                      Visualize
                    </button>
                    <button
                      className="landing-report-delete"
                      disabled={deleting === r.id}
                      onClick={() => handleDelete(r.id, r.report_name)}
                    >
                      {deleting === r.id ? "..." : "Delete"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!loading && reports.length === 0 && (
          <div className="landing-empty">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" style={{ marginBottom: 12, opacity: 0.4 }}>
              <rect x="4" y="4" width="32" height="32" rx="5" stroke="var(--text-muted)" strokeWidth="1.5" strokeDasharray="4 3" />
              <path d="M20 14v12M14 20h12" stroke="var(--text-muted)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <div>No saved reports yet</div>
            <div style={{ fontSize: 13, marginTop: 4 }}>Create your first report to get started.</div>
          </div>
        )}
      </div>
    </div>
  );
}
