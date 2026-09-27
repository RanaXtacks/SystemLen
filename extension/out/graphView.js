"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.GraphViewManager = void 0;
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const graphWebview_1 = require("./graphWebview");
class GraphViewManager {
    static currentPanel;
    static show(context, workspaceRoot, inMemoryGraph) {
        let graphData = inMemoryGraph;
        if (!graphData) {
            const config = vscode.workspace.getConfiguration("systemlens");
            const configuredPath = config.get("graphPath", "graph.json");
            let graphPath = path.isAbsolute(configuredPath)
                ? configuredPath
                : path.join(workspaceRoot, configuredPath);
            if (!fs.existsSync(graphPath)) {
                const fallbacks = [
                    path.join(workspaceRoot, ".systemlens", "graph.json"),
                    path.join(workspaceRoot, "graph.json"),
                    path.join(workspaceRoot, "benchmark", "benchmark_graph.json"),
                ];
                for (const fb of fallbacks) {
                    if (fs.existsSync(fb)) {
                        graphPath = fb;
                        break;
                    }
                }
            }
            if (fs.existsSync(graphPath)) {
                try {
                    const raw = fs.readFileSync(graphPath, "utf-8");
                    graphData = JSON.parse(raw);
                }
                catch (e) {
                    vscode.window.showErrorMessage(`SystemLens: Failed to read graph file: ${e}`);
                    return;
                }
            }
        }
        if (!graphData) {
            vscode.window.showErrorMessage("SystemLens: No dependency graph available. Rescan the project or wait for indexing to finish.");
            return;
        }
        if (GraphViewManager.currentPanel) {
            GraphViewManager.currentPanel.reveal(vscode.ViewColumn.One);
            GraphViewManager.currentPanel.webview.html = (0, graphWebview_1.getGraphWebviewContent)(graphData);
            return;
        }
        const panel = vscode.window.createWebviewPanel("systemlensGraph", "SystemLens: Dependency Graph", vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: true,
        });
        GraphViewManager.currentPanel = panel;
        panel.onDidDispose(() => {
            GraphViewManager.currentPanel = undefined;
        });
        panel.webview.onDidReceiveMessage((message) => {
            if (message.command === "analyzeTable") {
                vscode.commands.executeCommand("systemlens.analyzeTable", message.table);
            }
        }, undefined, context.subscriptions);
        panel.webview.html = (0, graphWebview_1.getGraphWebviewContent)(graphData);
    }
}
exports.GraphViewManager = GraphViewManager;
//# sourceMappingURL=graphView.js.map