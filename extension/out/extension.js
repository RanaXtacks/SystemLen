"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const child_process_1 = require("child_process");
const webview_1 = require("./webview");
function activate(context) {
    const disposable = vscode.commands.registerCommand("systemlens.whatTouchesThis", async () => {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
            return;
        }
        const rootPath = workspaceFolders[0].uri.fsPath;
        const graphPath = path.join(rootPath, "graph.json");
        let tableOptions = [];
        if (fs.existsSync(graphPath)) {
            try {
                const raw = fs.readFileSync(graphPath, "utf-8");
                const graphData = JSON.parse(raw);
                const nodes = graphData.nodes || [];
                tableOptions = nodes
                    .filter((n) => n.type === "table" || n.type === "view")
                    .map((n) => n.name)
                    .filter((name) => name && name !== "<unresolved_dynamic_query>");
                tableOptions = Array.from(new Set(tableOptions)).sort();
            }
            catch (e) {
                console.error("Failed to read graph.json for table options", e);
            }
        }
        const selected = await vscode.window.showInputBox({
            prompt: "Enter the table or entity name to analyze blast radius (e.g. 'users', 'orders')",
            placeHolder: tableOptions.length > 0 ? `e.g. ${tableOptions.slice(0, 3).join(", ")}` : "e.g. users",
        });
        if (!selected) {
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `SystemLens: Computing blast radius for '${selected}'...`,
            cancellable: false,
        }, async () => {
            return new Promise((resolve, reject) => {
                const cmd = `uv run systemlens impact --target "${selected}" --graph "${graphPath}" --json`;
                (0, child_process_1.exec)(cmd, { cwd: rootPath }, (error, stdout, stderr) => {
                    let impactData = null;
                    if (!error && stdout) {
                        try {
                            impactData = JSON.parse(stdout);
                        }
                        catch {
                            // Fallback
                        }
                    }
                    // Fallback to local graph.json traversal if CLI not in path or errored
                    if (!impactData && fs.existsSync(graphPath)) {
                        try {
                            const graphData = JSON.parse(fs.readFileSync(graphPath, "utf-8"));
                            impactData = computeSimpleFallbackImpact(selected, graphData);
                        }
                        catch (err) {
                            vscode.window.showErrorMessage(`SystemLens Error: ${err}`);
                            resolve();
                            return;
                        }
                    }
                    if (!impactData) {
                        vscode.window.showErrorMessage(`SystemLens: Could not compute impact for '${selected}'. Ensure graph.json exists or run 'systemlens analyze-python'.`);
                        resolve();
                        return;
                    }
                    const panel = vscode.window.createWebviewPanel("systemlensImpact", `SystemLens: ${selected}`, vscode.ViewColumn.Beside, { enableScripts: true });
                    panel.webview.html = (0, webview_1.getWebviewContent)(impactData);
                    resolve();
                });
            });
        });
    });
    context.subscriptions.push(disposable);
}
function computeSimpleFallbackImpact(target, graph) {
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    const lower = target.toLowerCase();
    const targetNode = nodes.find((n) => n.name?.toLowerCase() === lower ||
        n.id?.toLowerCase() === `table:${lower}` ||
        n.id?.toLowerCase().endsWith(`.${lower}`)) || { id: `table:${target}`, name: target, type: "table" };
    const impactedEdges = edges.filter((e) => e.target === targetNode.id || e.target?.toLowerCase() === `table:${lower}`);
    const funcs = [];
    const tables = [];
    for (const e of impactedEdges) {
        const srcNode = nodes.find((n) => n.id === e.source) || { id: e.source, name: e.source, type: "unknown" };
        const item = {
            node_id: srcNode.id,
            node_type: srcNode.type,
            name: srcNode.name || srcNode.id,
            confidence: e.confidence || 0.8,
            depth: 1,
            evidence_chain: [e.evidence || ""],
            metadata: srcNode.metadata || {},
        };
        if (srcNode.type === "function") {
            funcs.push(item);
        }
        else {
            tables.push(item);
        }
    }
    return {
        target: { id: targetNode.id, name: targetNode.name, type: targetNode.type },
        query: { max_depth: 2, total_impacted: funcs.length + tables.length },
        impacted_functions: funcs,
        impacted_files: [],
        impacted_tables: tables,
        ranked_items: [...funcs, ...tables],
        blind_spots: [
            {
                type: "dynamic_unresolved_sql",
                severity: "medium",
                message: "Dynamic SQL queries may access this table without static detection.",
            },
            {
                type: "cross_service_boundary",
                severity: "info",
                message: "Cross-service HTTP/RPC calls are not analyzed in V1.",
            },
        ],
    };
}
function deactivate() { }
//# sourceMappingURL=extension.js.map