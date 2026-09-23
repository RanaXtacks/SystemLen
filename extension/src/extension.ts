import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { exec } from "child_process";
import { getWebviewContent } from "./webview";

export function activate(context: vscode.ExtensionContext) {
  const disposable = vscode.commands.registerCommand(
    "systemlens.whatTouchesThis",
    async () => {
      const workspaceFolders = vscode.workspace.workspaceFolders;
      if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
        return;
      }

      const rootPath = workspaceFolders[0].uri.fsPath;
      const config = vscode.workspace.getConfiguration("systemlens");
      const configuredPath = config.get<string>("graphPath", "graph.json");
      const defaultDepth = config.get<number>("defaultDepth", 2);

      let graphPath = path.isAbsolute(configuredPath)
        ? configuredPath
        : path.join(rootPath, configuredPath);

      // Search fallbacks if not found at default location
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

      let tableOptions: string[] = [];
      if (fs.existsSync(graphPath)) {
        try {
          const raw = fs.readFileSync(graphPath, "utf-8");
          const graphData = JSON.parse(raw);
          const nodes = graphData.nodes || [];
          tableOptions = nodes
            .filter((n: any) => n.type === "table" || n.type === "view")
            .map((n: any) => n.name)
            .filter((name: string) => name && name !== "<unresolved_dynamic_query>");
          tableOptions = Array.from(new Set(tableOptions)).sort();
        } catch (e) {
          console.error("Failed to read graph for table options", e);
        }
      }

      // Detect selected word or symbol under cursor in active editor
      const editor = vscode.window.activeTextEditor;
      let initialValue = "";
      if (editor) {
        if (!editor.selection.isEmpty) {
          initialValue = editor.document.getText(editor.selection).trim();
        } else {
          const range = editor.document.getWordRangeAtPosition(editor.selection.active);
          if (range) {
            const word = editor.document.getText(range).trim();
            if (tableOptions.some((t) => t.toLowerCase() === word.toLowerCase())) {
              initialValue = word;
            } else if (word && !word.includes(" ")) {
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

      vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: `SystemLens: Computing blast radius for '${selected}'...`,
          cancellable: false,
        },
        async () => {
          return new Promise<void>((resolve, reject) => {
            const cmd = `uv run systemlens impact --target "${selected}" --graph "${graphPath}" --depth ${defaultDepth} --json`;
            exec(cmd, { cwd: rootPath }, (error, stdout, stderr) => {
              let impactData: any = null;

              if (!error && stdout) {
                try {
                  impactData = JSON.parse(stdout);
                } catch {
                  // Fallback
                }
              }

              // Fallback to local graph.json traversal if CLI not in path or errored
              if (!impactData && fs.existsSync(graphPath)) {
                try {
                  const graphData = JSON.parse(fs.readFileSync(graphPath, "utf-8"));
                  impactData = computeSimpleFallbackImpact(selected, graphData);
                } catch (err) {
                  vscode.window.showErrorMessage(`SystemLens Error: ${err}`);
                  resolve();
                  return;
                }
              }

              if (!impactData) {
                vscode.window.showErrorMessage(
                  `SystemLens: Could not compute impact for '${selected}'. Ensure graph.json exists or run 'systemlens analyze-python'.`
                );
                resolve();
                return;
              }

              const panel = vscode.window.createWebviewPanel(
                "systemlensImpact",
                `SystemLens: ${selected}`,
                vscode.ViewColumn.Beside,
                { enableScripts: true }
              );

              panel.webview.html = getWebviewContent(impactData);
              resolve();
            });
          });
        }
      );
    }
  );

  context.subscriptions.push(disposable);

  // Persistent Status Bar Button in bottom-right corner
  const statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.command = "systemlens.whatTouchesThis";
  statusBarItem.text = "$(eye) SystemLens";
  statusBarItem.tooltip = "SystemLens: What touches this? (Analyze Blast Radius)";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);
}

function computeSimpleFallbackImpact(target: string, graph: any): any {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const lower = target.toLowerCase();

  const targetNode = nodes.find(
    (n: any) =>
      n.name?.toLowerCase() === lower ||
      n.id?.toLowerCase() === `table:${lower}` ||
      n.id?.toLowerCase().endsWith(`.${lower}`)
  ) || { id: `table:${target}`, name: target, type: "table" };

  const impactedEdges = edges.filter(
    (e: any) => e.target === targetNode.id || e.target?.toLowerCase() === `table:${lower}`
  );

  const funcs: any[] = [];
  const tables: any[] = [];

  for (const e of impactedEdges) {
    const srcNode = nodes.find((n: any) => n.id === e.source) || { id: e.source, name: e.source, type: "unknown" };
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
    } else {
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

export function deactivate() {}
