import type { DataSourceConfig, VehicleConfig } from "../types";

interface Props {
  vehicles: VehicleConfig[];
  dataSources: DataSourceConfig;
}

export default function ConfigTab({ vehicles, dataSources }: Props) {
  const hasConfig = vehicles.length > 0 || dataSources.container_metrics;

  if (!hasConfig) {
    return (
      <div className="empty-state">
        <div className="icon">&#x2699;</div>
        <div>No configuration yet</div>
        <div style={{ fontSize: 12 }}>
          Ask the assistant to configure vehicles and data sources.
        </div>
      </div>
    );
  }

  return (
    <div>
      {vehicles.length > 0 && (
        <>
          <div className="code-label">Vehicles</div>
          <table className="data-table" style={{ marginBottom: 20 }}>
            <thead>
              <tr>
                <th>Vehicle ID</th>
                <th>Column</th>
                <th>Start</th>
                <th>Stop</th>
              </tr>
            </thead>
            <tbody>
              {vehicles.map((v) => (
                <tr key={v.vehicle_id}>
                  <td><code>{v.vehicle_id}</code></td>
                  <td>{v.col_name}</td>
                  <td>{v.start_ts}</td>
                  <td>{v.stop_ts || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {dataSources.container_metrics && (
        <>
          <div className="code-label">Data Sources</div>
          <div className="card">
            <div className="card-meta" style={{ flexDirection: "column", gap: 6 }}>
              <span>Container Metrics: <code style={{ fontSize: 11 }}>{dataSources.container_metrics}</code></span>
              <span>Channel Metrics: <code style={{ fontSize: 11 }}>{dataSources.channel_metrics}</code></span>
              <span>Channels: <code style={{ fontSize: 11 }}>{dataSources.channels.join(", ")}</code></span>
              {dataSources.aliases && (
                <span>Aliases: <code style={{ fontSize: 11 }}>{dataSources.aliases}</code></span>
              )}
            </div>
          </div>

          <div className="code-label" style={{ marginTop: 16 }}>Destination</div>
          <div className="card">
            <div className="card-meta" style={{ flexDirection: "column", gap: 6 }}>
              <span>Catalog: <code>{dataSources.destination_catalog}</code></span>
              <span>Schema: <code>{dataSources.destination_schema}</code></span>
              <span>Table Prefix: <code>{dataSources.table_prefix}</code></span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
