"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getGraphWebviewContent = getGraphWebviewContent;
function getGraphWebviewContent(graphData) {
    const safeData = JSON.stringify(graphData || { nodes: [], edges: [] }).replace(/</g, "\\u003c");
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SystemLens Dependency Graph</title>
  <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
  <style>
    :root {
      --bg: var(--vscode-editor-background, #1e1e2e);
      --fg: var(--vscode-editor-foreground, #cdd6f4);
      --border: var(--vscode-panel-border, #313244);
      --card-bg: var(--vscode-sideBar-background, #181825);
      --accent-blue: #3b82f6;
      --accent-green: #10b981;
      --accent-amber: #f59e0b;
      --accent-purple: #8b5cf6;
      --accent-red: #ef4444;
      --text-muted: #a6adc8;
    }

    body {
      margin: 0;
      padding: 0;
      width: 100vw;
      height: 100vh;
      overflow: hidden;
      background-color: var(--bg);
      color: var(--fg);
      font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
      display: flex;
    }

    #sidebar {
      width: 320px;
      min-width: 300px;
      background: var(--card-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      z-index: 10;
      padding: 16px;
      box-sizing: border-box;
      gap: 16px;
      overflow-y: auto;
    }

    h2 {
      margin: 0;
      font-size: 1.1rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .search-box {
      width: 100%;
      padding: 8px 12px;
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--fg);
      border-radius: 6px;
      box-sizing: border-box;
      outline: none;
    }
    .search-box:focus {
      border-color: var(--accent-blue);
    }

    .filter-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 0.85rem;
    }

    .filter-label {
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.5px;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
    }

    .legend-color {
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }

    #details-panel {
      border-top: 1px solid var(--border);
      padding-top: 12px;
      flex: 1;
    }

    .detail-card {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-size: 0.85rem;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .btn {
      background: var(--accent-blue);
      color: white;
      border: none;
      border-radius: 4px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 500;
      font-size: 0.85rem;
      text-align: center;
      margin-top: 8px;
    }
    .btn:hover {
      opacity: 0.9;
    }

    #graph-container {
      flex: 1;
      height: 100%;
      position: relative;
    }

    svg {
      width: 100%;
      height: 100%;
    }

    .link {
      stroke-opacity: 0.6;
    }
    .node circle {
      stroke: #fff;
      stroke-width: 1.5px;
      cursor: pointer;
      transition: r 0.2s ease;
    }
    .node text {
      font-size: 11px;
      fill: var(--fg);
      pointer-events: none;
      font-family: inherit;
    }
    .node.faded circle, .link.faded {
      opacity: 0.15;
    }
    .node.highlighted circle {
      stroke: #fbbf24;
      stroke-width: 3px;
    }
  </style>
</head>
<body>
  <div id="sidebar">
    <h2>🔍 SystemLens Graph</h2>
    <input type="text" id="search" class="search-box" placeholder="Search tables, functions...">

    <div class="filter-group">
      <div class="filter-label">Node Types</div>
      <label class="legend-item"><input type="checkbox" id="filter-table" checked> <div class="legend-color" style="background:#3b82f6;"></div> Tables / Views</label>
      <label class="legend-item"><input type="checkbox" id="filter-function" checked> <div class="legend-color" style="background:#10b981;"></div> Functions</label>
      <label class="legend-item"><input type="checkbox" id="filter-file" checked> <div class="legend-color" style="background:#64748b;"></div> Files</label>
      <label class="legend-item"><input type="checkbox" id="filter-dynamic" checked> <div class="legend-color" style="background:#ef4444;"></div> Dynamic / Unresolved</label>
    </div>

    <div class="filter-group">
      <div class="filter-label">Min Confidence: <span id="conf-val">0%</span></div>
      <input type="range" id="min-confidence" min="0" max="100" value="0">
    </div>

    <div id="details-panel">
      <div class="filter-label" style="margin-bottom: 8px;">Selected Entity</div>
      <div id="selected-info" class="detail-card">
        <em>Click any node in the graph to view properties and blast radius.</em>
      </div>
    </div>
  </div>

  <div id="graph-container">
    <svg id="graph-svg"></svg>
  </div>

  <script>
    const vscode = acquireVsCodeApi();
    const rawData = ${safeData};

    const typeColors = {
      table: "#3b82f6",
      view: "#3b82f6",
      partition: "#3b82f6",
      function: "#10b981",
      file: "#64748b",
      unresolved: "#ef4444"
    };

    function getNodeColor(d) {
      if (d.name === "<unresolved_dynamic_query>" || d.id === "table:unresolved") return "#ef4444";
      return typeColors[d.type] || "#8b5cf6";
    }

    const svg = d3.select("#graph-svg");
    const container = document.getElementById("graph-container");
    let width = container.clientWidth;
    let height = container.clientHeight;

    const g = svg.append("g");

    const zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    window.addEventListener("resize", () => {
      width = container.clientWidth;
      height = container.clientHeight;
      simulation.force("center", d3.forceCenter(width / 2, height / 2));
      simulation.alpha(0.3).restart();
    });

    let nodes = (rawData.nodes || []).map(d => ({ ...d }));
    let edges = (rawData.edges || []).map(d => ({ ...d }));

    // Edge map
    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    edges = edges.filter(e => nodeMap.has(e.source) && nodeMap.has(e.target));

    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(edges).id(d => d.id).distance(70))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(25));

    // Arrow markers
    svg.append("defs").selectAll("marker")
      .data(["end"])
      .enter().append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#64748b");

    const link = g.append("g")
      .attr("class", "links")
      .selectAll("line")
      .data(edges)
      .enter().append("line")
      .attr("class", "link")
      .attr("stroke", d => d.type === "dynamic_unresolved" ? "#ef4444" : "#64748b")
      .attr("stroke-width", d => Math.max(1, (d.confidence || 0.8) * 2.5))
      .attr("stroke-dasharray", d => (d.type === "static_sql_string" || d.type === "orm_call") ? "4,3" : "none")
      .attr("marker-end", "url(#arrow)");

    const node = g.append("g")
      .attr("class", "nodes")
      .selectAll("g")
      .data(nodes)
      .enter().append("g")
      .attr("class", "node")
      .call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended));

    node.append("circle")
      .attr("r", d => d.type === "table" ? 12 : d.type === "function" ? 9 : 7)
      .attr("fill", d => getNodeColor(d));

    node.append("text")
      .attr("dx", 14)
      .attr("dy", ".35em")
      .text(d => d.name || d.id);

    simulation.on("tick", () => {
      link
        .attr("x1", d => d.source.x)
        .attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x)
        .attr("y2", d => d.target.y);

      node.attr("transform", d => "translate(" + d.x + "," + d.y + ")");
    });

    let selectedNodeId = null;

    node.on("click", (event, d) => {
      event.stopPropagation();
      selectNode(d);
    });

    svg.on("click", () => {
      clearSelection();
    });

    function selectNode(d) {
      selectedNodeId = d.id;

      // Find reachable nodes (blast radius)
      const connectedNodeIds = new Set([d.id]);
      edges.forEach(e => {
        const sId = typeof e.source === 'object' ? e.source.id : e.source;
        const tId = typeof e.target === 'object' ? e.target.id : e.target;
        if (sId === d.id) connectedNodeIds.add(tId);
        if (tId === d.id) connectedNodeIds.add(sId);
      });

      node.classed("faded", n => !connectedNodeIds.has(n.id));
      node.classed("highlighted", n => n.id === d.id);
      link.classed("faded", l => {
        const sId = typeof l.source === 'object' ? l.source.id : l.source;
        const tId = typeof l.target === 'object' ? l.target.id : l.target;
        return !connectedNodeIds.has(sId) || !connectedNodeIds.has(tId);
      });

      // Update sidebar
      const info = document.getElementById("selected-info");
      const cleanName = d.name || d.id;
      const isTable = d.type === "table" || d.type === "view";

      info.innerHTML = \`
        <div><strong>\${cleanName}</strong></div>
        <div>Type: <code>\${d.type}</code></div>
        <div>ID: <code>\${d.id}</code></div>
        \${d.metadata?.file ? '<div>File: <code>' + d.metadata.file + '</code></div>' : ''}
        <div>Connected: \${connectedNodeIds.size - 1} entities</div>
        \${isTable ? '<button class="btn" onclick="analyzeTable(\\'' + cleanName + '\\')">⚡ Analyze Blast Radius</button>' : ''}
      \`;
    }

    function clearSelection() {
      selectedNodeId = null;
      node.classed("faded", false).classed("highlighted", false);
      link.classed("faded", false);
      document.getElementById("selected-info").innerHTML = '<em>Click any node in the graph to view properties and blast radius.</em>';
    }

    window.analyzeTable = function(tableName) {
      vscode.postMessage({
        command: "analyzeTable",
        table: tableName
      });
    };

    // Search filter
    document.getElementById("search").addEventListener("input", (e) => {
      const query = e.target.value.toLowerCase().trim();
      if (!query) {
        clearSelection();
        return;
      }
      const match = nodes.find(n => (n.name && n.name.toLowerCase().includes(query)) || n.id.toLowerCase().includes(query));
      if (match) {
        selectNode(match);
        // Pan to matched node
        svg.transition().duration(500).call(
          zoom.transform,
          d3.zoomIdentity.translate(width / 2 - match.x, height / 2 - match.y).scale(1.2)
        );
      }
    });

    function dragstarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragended(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }
  </script>
</body>
</html>`;
}
//# sourceMappingURL=graphWebview.js.map