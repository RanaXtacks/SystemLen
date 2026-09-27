import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { exec } from "child_process";
import { getWebviewContent } from "./webview";
import { SystemLensTreeProvider } from "./treeView";
import { SystemLensCodeLensProvider } from "./codeLens";
import { SystemLensDecorationProvider } from "./decorations";
import { GraphViewManager } from "./graphView";
import { ProjectScanner } from "./engine/scanner/projectScanner";

export function activate(context: vscode.ExtensionContext) {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  const rootPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : "";

  // 1. Providers Initialization
  let treeProvider: SystemLensTreeProvider | null = null;
  let codeLensProvider: SystemLensCodeLensProvider | null = null;
  const decorationProvider = new SystemLensDecorationProvider();
  let scanner: ProjectScanner | null = null;

  // 2. Persistent Status Bar Buttons
  const statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.command = "systemlens.whatTouchesThis";
  statusBarItem.text = "$(eye) SystemLens";
  statusBarItem.tooltip = "SystemLens: What touches this? (Analyze Blast Radius)";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  const graphStatusItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    99
  );
  graphStatusItem.command = "systemlens.showGraph";
  graphStatusItem.text = "$(graph) Graph";
  graphStatusItem.tooltip = "SystemLens: Open Interactive Dependency Graph";
  graphStatusItem.show();
  context.subscriptions.push(graphStatusItem);

  // 3. Scanner & Workspace Auto-Discovery
  async function runWorkspaceScan(showNotification = false): Promise<void> {
    if (!scanner || !rootPath) return;

    statusBarItem.text = "$(sync~spin) SystemLens: Indexing...";
    try {
      const graph = await scanner.scanProject((_status, msg) => {
        statusBarItem.text = `$(sync~spin) ${msg}`;
      });

      treeProvider?.setGraphData(graph);
      codeLensProvider?.setGraphData(graph);

      const tableNodes = (graph.nodes || []).filter(
        (n: any) =>
          (n.type === "table" || n.type === "view") &&
          n.name !== "<unresolved_dynamic_query>"
      );
      const tableCount = tableNodes.length;

      statusBarItem.text = `$(eye) SystemLens: ${tableCount} tables`;
      statusBarItem.tooltip = `SystemLens: Found ${tableCount} tables, ${graph.nodes.length} nodes across workspace.\nClick to analyze blast radius.`;

      if (showNotification) {
        vscode.window.showInformationMessage(
          `SystemLens: Workspace indexed successfully (${tableCount} tables, ${graph.nodes.length} nodes).`
        );
      }
    } catch (err) {
      console.error("[SystemLens] Background scan error:", err);
      statusBarItem.text = "$(eye) SystemLens";
      statusBarItem.tooltip = "SystemLens: What touches this? (Analyze Blast Radius)";
    }
  }

  if (rootPath) {
    scanner = new ProjectScanner(rootPath);

    treeProvider = new SystemLensTreeProvider(rootPath);
    vscode.window.registerTreeDataProvider("systemlens-explorer", treeProvider);

    codeLensProvider = new SystemLensCodeLensProvider(rootPath);
    const docSelector: vscode.DocumentSelector = [
      { language: "python", scheme: "file" },
      { language: "javascript", scheme: "file" },
      { language: "typescript", scheme: "file" },
      { language: "javascriptreact", scheme: "file" },
      { language: "typescriptreact", scheme: "file" },
      { language: "go", scheme: "file" },
      { language: "java", scheme: "file" },
      { language: "ruby", scheme: "file" },
      { language: "php", scheme: "file" },
      { language: "rust", scheme: "file" },
      { language: "csharp", scheme: "file" },
      { language: "c", scheme: "file" },
      { language: "cpp", scheme: "file" },
      { language: "sql", scheme: "file" },
    ];
    context.subscriptions.push(
      vscode.languages.registerCodeLensProvider(docSelector, codeLensProvider)
    );

    // Initial background scan on workspace open
    const autoScanOnOpen = vscode.workspace
      .getConfiguration("systemlens")
      .get<boolean>("autoScanOnOpen", true);

    if (autoScanOnOpen) {
      runWorkspaceScan(false);
    }

    // Incremental update on file save
    vscode.workspace.onDidSaveTextDocument(
      (doc) => {
        const autoScanOnSave = vscode.workspace
          .getConfiguration("systemlens")
          .get<boolean>("autoScanOnSave", true);

        if (autoScanOnSave && scanner) {
          scanner.updateFile(doc.uri.fsPath);
          const updatedGraph = scanner.getGraph();
          if (updatedGraph) {
            treeProvider?.setGraphData(updatedGraph);
            codeLensProvider?.setGraphData(updatedGraph);
            const tableCount = (updatedGraph.nodes || []).filter(
              (n: any) =>
                (n.type === "table" || n.type === "view") &&
                n.name !== "<unresolved_dynamic_query>"
            ).length;
            statusBarItem.text = `$(eye) SystemLens: ${tableCount} tables`;
          }
        }
      },
      null,
      context.subscriptions
    );

    // Watcher for external graph.json updates
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

  // 4. Editor Decorations
  if (vscode.window.activeTextEditor) {
    decorationProvider.updateDecorations(vscode.window.activeTextEditor);
  }
  vscode.window.onDidChangeActiveTextEditor(
    (editor) => {
      decorationProvider.updateDecorations(editor);
    },
    null,
    context.subscriptions
  );
  vscode.workspace.onDidChangeTextDocument(
    (event) => {
      if (
        vscode.window.activeTextEditor &&
        event.document === vscode.window.activeTextEditor.document
      ) {
        decorationProvider.updateDecorations(vscode.window.activeTextEditor);
      }
    },
    null,
    context.subscriptions
  );
  context.subscriptions.push(decorationProvider);

  // 5. Command: Rescan Workspace & Rebuild Graph
  context.subscriptions.push(
    vscode.commands.registerCommand("systemlens.rescanProject", async () => {
      if (!rootPath) {
        vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
        return;
      }
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "SystemLens: Rescanning workspace...",
          cancellable: false,
        },
        async () => {
          await runWorkspaceScan(true);
        }
      );
    })
  );

  // 6. Command: Refresh Explorer
  context.subscriptions.push(
    vscode.commands.registerCommand("systemlens.refreshExplorer", () => {
      if (scanner?.getGraph()) {
        treeProvider?.setGraphData(scanner.getGraph());
        codeLensProvider?.setGraphData(scanner.getGraph());
      } else {
        treeProvider?.refresh();
        codeLensProvider?.refresh();
      }
      vscode.window.showInformationMessage("SystemLens: Explorer & CodeLens refreshed.");
    })
  );

  // 7. Command: Show Interactive Graph View
  context.subscriptions.push(
    vscode.commands.registerCommand("systemlens.showGraph", () => {
      if (!rootPath) {
        vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
        return;
      }
      GraphViewManager.show(context, rootPath, scanner?.getGraph());
    })
  );

  // 8. Helper: Compute and Display Blast Radius for any table
  async function computeAndShowImpact(target: string) {
    if (!rootPath) {
      vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
      return;
    }

    const config = vscode.workspace.getConfiguration("systemlens");
    const defaultDepth = config.get<number>("defaultDepth", 2);

    // Fast Path: Use in-memory NativeImpactEngine (instantaneous, 0 dependencies)
    const impactEngine = scanner?.getImpactEngine();
    if (impactEngine) {
      const impactData = impactEngine.blastRadius(target, defaultDepth);
      if (impactData && (impactData.impacted_functions.length > 0 || impactData.impacted_tables.length > 0 || impactData.blind_spots.length > 0 || impactData.query.total_impacted >= 0)) {
        const panel = vscode.window.createWebviewPanel(
          "systemlensImpact",
          `SystemLens: ${target}`,
          vscode.ViewColumn.Beside,
          { enableScripts: true }
        );
        panel.webview.html = getWebviewContent(impactData);
        return;
      }
    }

    // Fallback: Read from disk or call CLI
    const configuredPath = config.get<string>("graphPath", "graph.json");
    let graphPath = path.isAbsolute(configuredPath)
      ? configuredPath
      : path.join(rootPath, configuredPath);

    if (!fs.existsSync(graphPath)) {
      const fallbacks = [
        path.join(rootPath, ".systemlens", "graph.json"),
        path.join(rootPath, "graph.json"),
        path.join(rootPath, "benchmark", "benchmark_graph.json"),
      ];
      for (const fb of fallbacks) {
        if (fs.existsSync(fb)) {
          graphPath = fb;
          break;
        }
      }
    }

    return vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `SystemLens: Computing blast radius for '${target}'...`,
        cancellable: false,
      },
      async () => {
        return new Promise<void>((resolve) => {
          const cmd = `uv run systemlens impact --target "${target}" --graph "${graphPath}" --depth ${defaultDepth} --json`;
          exec(cmd, { cwd: rootPath }, (error, stdout, _stderr) => {
            let impactData: any = null;

            if (!error && stdout) {
              try {
                impactData = JSON.parse(stdout);
              } catch {
                // Ignore parse errors, try fallback
              }
            }

            // Fallback to local graph.json traversal if CLI errored
            if (!impactData && fs.existsSync(graphPath)) {
              try {
                const graphData = JSON.parse(fs.readFileSync(graphPath, "utf-8"));
                impactData = computeSimpleFallbackImpact(target, graphData);
              } catch (err) {
                vscode.window.showErrorMessage(`SystemLens Error: ${err}`);
                resolve();
                return;
              }
            }

            if (!impactData) {
              vscode.window.showErrorMessage(
                `SystemLens: Could not compute impact for '${target}'. Run 'Rescan Workspace' to index your tables.`
              );
              resolve();
              return;
            }

            const panel = vscode.window.createWebviewPanel(
              "systemlensImpact",
              `SystemLens: ${target}`,
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

  // 9. Command: Analyze Table (direct invocation from treeView or CodeLens)
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "systemlens.analyzeTable",
      async (tableName: string) => {
        if (!tableName) return;
        await computeAndShowImpact(tableName);
      }
    )
  );

  // 10. Command: What touches this? (Interactive prompt)
  const whatTouchesThis = vscode.commands.registerCommand(
    "systemlens.whatTouchesThis",
    async () => {
      if (!rootPath) {
        vscode.window.showErrorMessage("SystemLens: Open a workspace folder first.");
        return;
      }

      let tableOptions: string[] = [];

      // 1. From in-memory graph
      const memoryGraph = scanner?.getGraph();
      if (memoryGraph && memoryGraph.nodes) {
        tableOptions = memoryGraph.nodes
          .filter((n: any) => (n.type === "table" || n.type === "view") && n.name !== "<unresolved_dynamic_query>")
          .map((n: any) => n.name)
          .filter(Boolean);
      }

      // 2. Fallback to graph file
      if (tableOptions.length === 0) {
        const fallbacks = [
          path.join(rootPath, ".systemlens", "graph.json"),
          path.join(rootPath, "graph.json"),
          path.join(rootPath, "benchmark", "benchmark_graph.json"),
        ];
        for (const fb of fallbacks) {
          if (fs.existsSync(fb)) {
            try {
              const raw = fs.readFileSync(fb, "utf-8");
              const graphData = JSON.parse(raw);
              const nodes = graphData.nodes || [];
              tableOptions = nodes
                .filter((n: any) => (n.type === "table" || n.type === "view") && n.name !== "<unresolved_dynamic_query>")
                .map((n: any) => n.name)
                .filter(Boolean);
              if (tableOptions.length > 0) break;
            } catch {
              // Ignore
            }
          }
        }
      }

      tableOptions = Array.from(new Set(tableOptions)).sort();

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
        placeHolder: tableOptions.length > 0 ? `e.g. ${tableOptions.slice(0, 4).join(", ")}` : "e.g. users",
        value: initialValue,
      });

      if (!selected) {
        return;
      }

      await computeAndShowImpact(selected);
    }
  );

  context.subscriptions.push(whatTouchesThis);
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
