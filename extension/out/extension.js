"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");
const child_process_1 = require("child_process");
const webview_1 = require("./webview");
const treeView_1 = require("./treeView");
const codeLens_1 = require("./codeLens");
const decorations_1 = require("./decorations");
const graphView_1 = require("./graphView");
function activate(context) {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    const rootPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : "";
    // 1. Providers Initialization
    let treeProvider = null;
    let codeLensProvider = null;
    const decorationProvider = new decorations_1.SystemLensDecorationProvider();
    if (rootPath) {
        treeProvider = new treeView_1.SystemLensTreeProvider(rootPath);
        vscode.window.registerTreeDataProvider("systemlens-explorer", treeProvider);
        codeLensProvider = new codeLens_1.SystemLensCodeLensProvider(rootPath);
        const docSelector = [
            { language: "python", scheme: "file" },
            { language: "javascript", scheme: "file" },
            { language: "typescript", scheme: "file" },
        ];
        context.subscriptions.push(vscode.languages.registerCodeLensProvider(docSelector, codeLensProvider));
        // Watcher for graph.json updates
        const watcher = vscode.workspace.createFileSystemWatcher("**/graph.json");
        watcher.onDidChange(() => {
            treeProvider?.refresh();
            codeLensProvider?.refresh();
        });
        watcher.onDidCreate(() => {
            treeProvider?.refresh();
            codeLensProvider?.refresh();
        });
        watcher.onDidDelete(() => {
            treeProvider?.refresh();
            codeLensProvider?.refresh();
        });
        context.subscriptions.push(watcher);
    }
    // 2. Decorations Events
    if (vscode.window.activeTextEditor) {
        decorationProvider.updateDecorations(vscode.window.activeTextEditor);
    }
    vscode.window.onDidChangeActiveTextEditor((editor) => {
        decorationProvider.updateDecorations(editor);
    }, null, context.subscriptions);
    vscode.workspace.onDidChangeTextDocument((event) => {
        if (vscode.window.activeTextEditor &&
            event.document === vscode.window.activeTextEditor.document) {
            decorationProvider.updateDecorations(vscode.window.activeTextEditor);
        }
    }, null, context.subscriptions);
    context.subscriptions.push(decorationProvider);
    // 3. Command: Refresh Explorer
    context.subscriptions.push(vscode.commands.registerCommand("systemlens.refreshExplorer", () => {
        treeProvider?.refresh();
        codeLensProvider?.refresh();
        vscode.window.showInformationMessage("SystemLens: Explorer & CodeLens refreshed.");
    }));
    // 4. Command: Show Interactive Graph View
    context.subscriptions.push(vscode.commands.registerCommand("systemlens.showGraph", () => {
        if (!rootPath) {
            vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
            return;
        }
        graphView_1.GraphViewManager.show(context, rootPath);
    }));
    // 5. Helper: Compute and Display Blast Radius for any table
    async function computeAndShowImpact(target) {
        if (!rootPath) {
            vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
            return;
        }
        const config = vscode.workspace.getConfiguration("systemlens");
        const configuredPath = config.get("graphPath", "graph.json");
        const defaultDepth = config.get("defaultDepth", 2);
        let graphPath = path.isAbsolute(configuredPath)
            ? configuredPath
            : path.join(rootPath, configuredPath);
        if (!fs.existsSync(graphPath)) {
            const fallbacks = [
                path.join(rootPath, "graph.json"),
                path.join(rootPath, "benchmark", "benchmark_graph.json"),
                path.join(rootPath, ".systemlens", "graph.json"),
            ];
            for (const fb of fallbacks) {
                if (fs.existsSync(fb)) {
                    graphPath = fb;
                    break;
                }
            }
        }
        return vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `SystemLens: Computing blast radius for '${target}'...`,
            cancellable: false,
        }, async () => {
            return new Promise((resolve) => {
                const cmd = `uv run systemlens impact --target "${target}" --graph "${graphPath}" --depth ${defaultDepth} --json`;
                (0, child_process_1.exec)(cmd, { cwd: rootPath }, (error, stdout, stderr) => {
                    let impactData = null;
                    if (!error && stdout) {
                        try {
                            impactData = JSON.parse(stdout);
                        }
                        catch {
                            // Ignore parse errors, try fallback
                        }
                    }
                    // Fallback to local graph.json traversal if CLI errored
                    if (!impactData && fs.existsSync(graphPath)) {
                        try {
                            const graphData = JSON.parse(fs.readFileSync(graphPath, "utf-8"));
                            impactData = computeSimpleFallbackImpact(target, graphData);
                        }
                        catch (err) {
                            vscode.window.showErrorMessage(`SystemLens Error: ${err}`);
                            resolve();
                            return;
                        }
                    }
                    if (!impactData) {
                        vscode.window.showErrorMessage(`SystemLens: Could not compute impact for '${target}'. Ensure graph.json exists or run 'systemlens analyze-python'.`);
                        resolve();
                        return;
                    }
                    const panel = vscode.window.createWebviewPanel("systemlensImpact", `SystemLens: ${target}`, vscode.ViewColumn.Beside, { enableScripts: true });
                    panel.webview.html = (0, webview_1.getWebviewContent)(impactData);
                    resolve();
                });
            });
        });
    }
    // 6. Command: Analyze Table (direct invocation from treeView or CodeLens)
    context.subscriptions.push(vscode.commands.registerCommand("systemlens.analyzeTable", async (tableName) => {
        if (!tableName)
            return;
        await computeAndShowImpact(tableName);
    }));
    // 7. Command: What touches this? (Interactive prompt)
    const whatTouchesThis = vscode.commands.registerCommand("systemlens.whatTouchesThis", async () => {
        if (!rootPath) {
            vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
            return;
        }
        const config = vscode.workspace.getConfiguration("systemlens");
        const configuredPath = config.get("graphPath", "graph.json");
        let graphPath = path.isAbsolute(configuredPath)
            ? configuredPath
            : path.join(rootPath, configuredPath);
        if (!fs.existsSync(graphPath)) {
            const fallbacks = [
                path.join(rootPath, "graph.json"),
                path.join(rootPath, "benchmark", "benchmark_graph.json"),
                path.join(rootPath, ".systemlens", "graph.json"),
            ];
            for (const fb of fallbacks) {
                if (fs.existsSync(fb)) {
                    graphPath = fb;
                    break;
                }
            }
        }
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
                console.error("Failed to read graph for table options", e);
            }
        }
        // Detect selected word or symbol under cursor in active editor
        const editor = vscode.window.activeTextEditor;
        let initialValue = "";
        if (editor) {
            if (!editor.selection.isEmpty) {
                initialValue = editor.document.getText(editor.selection).trim();
            }
            else {
                const range = editor.document.getWordRangeAtPosition(editor.selection.active);
                if (range) {
                    const word = editor.document.getText(range).trim();
                    if (tableOptions.some((t) => t.toLowerCase() === word.toLowerCase())) {
                        initialValue = word;
                    }
                    else if (word && !word.includes(" ")) {
                        initialValue = word;
                    }
                }
            }
        }
        const selected = await vscode.window.showInputBox({
            prompt: "Enter the table or entity name to analyze blast radius (e.g. 'users', 'orders')",
            placeHolder: tableOptions.length > 0 ? `e.g. ${tableOptions.slice(0, 3).join(", ")}` : "e.g. users",
            value: initialValue,
        });
        if (!selected) {
            return;
        }
        await computeAndShowImpact(selected);
    });
    context.subscriptions.push(whatTouchesThis);
    // 8. Persistent Status Bar Button
    const statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = "systemlens.whatTouchesThis";
    statusBarItem.text = "$(eye) SystemLens";
    statusBarItem.tooltip = "SystemLens: What touches this? (Analyze Blast Radius)";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
    // Status Bar Button for Graph
    const graphStatusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
    graphStatusItem.command = "systemlens.showGraph";
    graphStatusItem.text = "$(graph) Graph";
    graphStatusItem.tooltip = "SystemLens: Open Interactive Dependency Graph";
    graphStatusItem.show();
    context.subscriptions.push(graphStatusItem);
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