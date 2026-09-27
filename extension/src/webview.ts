export function getWebviewContent(data: any): string {
  const target = data.target || {};
  const query = data.query || {};
  const funcs = data.impacted_functions || [];
  const files = data.impacted_files || [];
  const tables = data.impacted_tables || [];
  const blindSpots = data.blind_spots || [];

  const getConfBadge = (conf: number) => {
    const pct = Math.round(conf * 100);
    if (pct >= 80) {
      return `<span class="badge badge-high">${pct}% Confidence</span>`;
    } else if (pct >= 50) {
      return `<span class="badge badge-medium">${pct}% Confidence</span>`;
    } else {
      return `<span class="badge badge-low">${pct}% Confidence</span>`;
    }
  };

  const funcRows = funcs.map((fn: any) => `
    <div class="card item-card">
      <div class="item-header">
        <div class="item-title">
          <span class="icon">⚡</span>
          <strong>${fn.name}</strong>
          ${getConfBadge(fn.confidence)}
        </div>
        <span class="hop-tag">Hop ${fn.depth}</span>
      </div>
      <div class="item-meta">
        <code>${fn.metadata?.file || ""}${fn.metadata?.lineno ? ":" + fn.metadata.lineno : ""}</code>
      </div>
      ${fn.evidence_chain && fn.evidence_chain.length > 0 ? `
        <div class="evidence-preview">
          ${fn.evidence_chain[0]}
        </div>
      ` : ""}
    </div>
  `).join("") || `<div class="empty-state">No directly impacted functions detected.</div>`;

  const fileRows = files.map((fl: any) => `
    <div class="card item-card">
      <div class="item-header">
        <div class="item-title">
          <span class="icon">📄</span>
          <strong>${fl.name}</strong>
          ${getConfBadge(fl.confidence)}
        </div>
        <span class="hop-tag">Hop ${fl.depth}</span>
      </div>
    </div>
  `).join("") || `<div class="empty-state">No directly impacted files detected.</div>`;

  const tableRows = tables.map((tb: any) => `
    <div class="card item-card">
      <div class="item-header">
        <div class="item-title">
          <span class="icon">🗄️</span>
          <strong>${tb.name}</strong>
          ${getConfBadge(tb.confidence)}
        </div>
        <span class="hop-tag">Hop ${tb.depth}</span>
      </div>
    </div>
  `).join("") || `<div class="empty-state">No downstream tables impacted.</div>`;

  const blindSpotRows = blindSpots.map((bs: any) => `
    <div class="blind-spot-card severity-${bs.severity || "info"}">
      <div class="bs-title">
        <span class="bs-badge">${(bs.severity || "info").toUpperCase()}</span>
        <span>${bs.message}</span>
      </div>
      ${bs.functions && bs.functions.length > 0 ? `
        <div class="bs-details">
          Affected calls: ${bs.functions.slice(0, 5).map((f: string) => `<code>${f}</code>`).join(", ")}
        </div>
      ` : ""}
    </div>
  `).join("");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SystemLens Blast Radius: ${target.name || ""}</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --high-conf: #10b981;
      --med-conf: #f59e0b;
      --low-conf: #f43f5e;
    }
    body {
      background-color: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding: 24px;
      margin: 0;
      line-height: 1.5;
    }
    .header {
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }
    .target-badge {
      display: inline-block;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    h1 {
      margin: 0 0 8px 0;
      font-size: 26px;
      font-weight: 700;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 14px 18px;
    }
    .stat-val {
      font-size: 28px;
      font-weight: 700;
      color: var(--accent);
    }
    .stat-label {
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .section-title {
      font-size: 17px;
      font-weight: 600;
      margin: 24px 0 12px 0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 14px 16px;
      margin-bottom: 10px;
    }
    .item-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .item-title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
    }
    .badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 600;
    }
    .badge-high {
      background: rgba(16, 185, 129, 0.15);
      color: var(--high-conf);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .badge-medium {
      background: rgba(245, 158, 11, 0.15);
      color: var(--med-conf);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .badge-low {
      background: rgba(244, 63, 94, 0.15);
      color: var(--low-conf);
      border: 1px solid rgba(244, 63, 94, 0.3);
    }
    .hop-tag {
      font-size: 12px;
      color: var(--text-muted);
      background: #0f172a;
      padding: 2px 8px;
      border-radius: 4px;
    }
    .item-meta {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 6px;
    }
    code {
      background: #090d16;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .evidence-preview {
      font-size: 12px;
      color: var(--text-muted);
      background: #0a0e1a;
      padding: 8px 12px;
      border-radius: 6px;
      margin-top: 8px;
      border-left: 3px solid var(--accent);
    }
    .blind-spot-card {
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 10px;
    }
    .severity-high {
      background: rgba(244, 63, 94, 0.1);
      border: 1px solid rgba(244, 63, 94, 0.3);
    }
    .severity-medium {
      background: rgba(245, 158, 11, 0.1);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .severity-info {
      background: rgba(56, 189, 248, 0.08);
      border: 1px solid rgba(56, 189, 248, 0.2);
    }
    .bs-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 500;
    }
    .bs-badge {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 700;
      background: rgba(0, 0, 0, 0.3);
    }
    .bs-details {
      margin-top: 6px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .empty-state {
      color: var(--text-muted);
      font-style: italic;
      padding: 12px 0;
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="target-badge">${target.type || "TABLE"}</span>
    <h1>Blast Radius: ${target.name || "Unknown"}</h1>
    <div style="color: var(--text-muted); font-size: 13px;">
      Resolved Target ID: <code>${target.id || ""}</code> &bull; Reachability Depth: <strong>${query.max_depth || 2} hops</strong>
    </div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-val">${query.total_impacted || 0}</div>
      <div class="stat-label">Total Impacted</div>
    </div>
    <div class="stat-card">
      <div class="stat-val">${funcs.length}</div>
      <div class="stat-label">Functions</div>
    </div>
    <div class="stat-card">
      <div class="stat-val">${files.length}</div>
      <div class="stat-label">Files</div>
    </div>
    <div class="stat-card">
      <div class="stat-val">${tables.length}</div>
      <div class="stat-label">Downstream DB</div>
    </div>
  </div>

  <div class="section-title">⚡ Impacted Code Functions (Ranked by Path Confidence)</div>
  ${funcRows}

  <div class="section-title">📄 Impacted Files</div>
  ${fileRows}

  <div class="section-title">🗄️ Impacted Downstream Tables (FKs / Views)</div>
  ${tableRows}

  <div class="section-title">🛡️ Blind Spots & Unanalyzed Boundaries (Honesty Layer)</div>
  ${blindSpotRows}
</body>
</html>`;
}
