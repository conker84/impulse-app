import { ReportIcon } from "./LandingScreen";

interface Props {
  active: "landing" | "editor" | "visualize" | "timeseries";
  onHome: () => void;
  onNewReport: () => void;
  onTimeSeries: () => void;
  onSettings?: () => void;
}

export default function AppSidebar({ active, onHome, onNewReport, onTimeSeries, onSettings }: Props) {
  return (
    <nav className="app-nav">
      <button className="app-nav-logo" onClick={onHome} title="Impulse — Home">
        <ReportIcon size={32} />
      </button>

      <button
        className={`app-nav-item${active === "editor" ? " active" : ""}`}
        onClick={onNewReport}
        title="Create New Report"
      >
        <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
          <path d="M9 2v14M2 9h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
        <span>New Report</span>
      </button>

      <button
        className={`app-nav-item${active === "timeseries" ? " active" : ""}`}
        onClick={onTimeSeries}
        title="Explore Time Series"
      >
        <svg width="22" height="22" viewBox="0 0 18 18" fill="none">
          <polyline points="2,14 6,8 10,11 14,4 17,6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>Explore Time Series</span>
      </button>

      {onSettings && (
        <button className="app-nav-item app-nav-settings" onClick={onSettings} title="Settings">
          <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
            <path d="M8.5 1.5a1.5 1.5 0 013 0v.7a6.5 6.5 0 011.7.7l.5-.5a1.5 1.5 0 012.12 2.12l-.5.5c.3.5.5 1.1.7 1.7h.7a1.5 1.5 0 010 3h-.7c-.2.6-.4 1.2-.7 1.7l.5.5a1.5 1.5 0 01-2.12 2.12l-.5-.5c-.5.3-1.1.5-1.7.7v.7a1.5 1.5 0 01-3 0v-.7a6.5 6.5 0 01-1.7-.7l-.5.5a1.5 1.5 0 01-2.12-2.12l.5-.5A6.5 6.5 0 014 10.5h-.7a1.5 1.5 0 010-3h.7c.2-.6.4-1.2.7-1.7l-.5-.5A1.5 1.5 0 016.3 3.18l.5.5c.5-.3 1.1-.5 1.7-.7V1.5zM10 7a3 3 0 100 6 3 3 0 000-6z" fill="currentColor" />
          </svg>
          <span>Settings</span>
        </button>
      )}
    </nav>
  );
}
