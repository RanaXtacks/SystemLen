import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

export class SystemLensCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses: vscode.EventEmitter<void> =
    new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses: vscode.Event<void> =
    this._onDidChangeCodeLenses.event;

  private graphData: any = null;
  private cachedFileMap: Map<string, Map<string, string[]>> = new Map();

  constructor(private workspaceRoot: string) {
    this.reloadGraph();
  }

  public reloadGraph(): void {
    const config = vscode.workspace.getConfiguration("systemlens");
    const configuredPath = config.get<string>("graphPath", "graph.json");

    let candidate = path.isAbsolute(configuredPath)
      ? configuredPath
      : path.join(this.workspaceRoot, configuredPath);

    if (!fs.existsSync(candidate)) {
      const fallbacks = [
        path.join(this.workspaceRoot, "graph.json"),
        path.join(this.workspaceRoot, "benchmark", "benchmark_graph.json"),
        path.join(this.workspaceRoot, ".systemlens", "graph.json"),
      ];
      for (const fb of fallbacks) {
        if (fs.existsSync(fb)) {
          candidate = fb;
          break;
        }
      }
    }

    if (fs.existsSync(candidate)) {
      try {
        const raw = fs.readFileSync(candidate, "utf-8");
        this.graphData = JSON.parse(raw);
        this.buildIndex();
      } catch (e) {
        this.graphData = null;
      }
    } else {
      this.graphData = null;
    }
  }

  public refresh(): void {
    this.reloadGraph();
    this._onDidChangeCodeLenses.fire();
  }

  /**
   * Builds an index: normalized_file_path -> (func_name -> [touched_table_names])
   */
  private buildIndex(): void {
    this.cachedFileMap.clear();
    if (!this.graphData) {
      return;
    }

    const nodes = this.graphData.nodes || [];
    const edges = this.graphData.edges || [];

    // Map func_id to touched tables
    const funcToTables = new Map<string, Set<string>>();
    for (const e of edges) {
      const target: string = e.target || "";
      if (
        target.startsWith("table:") &&
        target !== "table:unresolved" &&
        !target.includes("<unresolved_dynamic_query>")
      ) {
        const tableName = target.replace("table:", "").split(".").pop() || "";
        if (!funcToTables.has(e.source)) {
          funcToTables.set(e.source, new Set());
        }
        funcToTables.get(e.source)!.add(tableName);
      }
    }

    // Map files to functions
    for (const n of nodes) {
      if (n.type === "function" && funcToTables.has(n.id)) {
        const filePath =
          n.metadata?.file ||
          n.metadata?.filepath ||
          n.metadata?.path ||
          (n.id.split(":")[1] || "");

        const normalizedFile = filePath.replace(/\\/g, "/").toLowerCase();
        const funcName = n.name || n.id.split(":").pop();

        if (!this.cachedFileMap.has(normalizedFile)) {
          this.cachedFileMap.set(normalizedFile, new Map());
        }

        const touched = Array.from(funcToTables.get(n.id)!);
        this.cachedFileMap.get(normalizedFile)!.set(funcName, touched);
      }
    }
  }

  provideCodeLenses(
    document: vscode.TextDocument,
    token: vscode.CancellationToken
  ): vscode.CodeLens[] | Thenable<vscode.CodeLens[]> {
    if (!this.graphData || this.cachedFileMap.size === 0) {
      return [];
    }

    const docPath = document.uri.fsPath.replace(/\\/g, "/").toLowerCase();

    // Check if docPath matches any indexed file
    let fileFuncMap: Map<string, string[]> | undefined;
    for (const [indexedFile, funcMap] of this.cachedFileMap.entries()) {
      if (
        docPath.endsWith("/" + indexedFile) ||
        docPath === indexedFile ||
        indexedFile.endsWith("/" + path.basename(docPath).toLowerCase())
      ) {
        fileFuncMap = funcMap;
        break;
      }
    }

    if (!fileFuncMap || fileFuncMap.size === 0) {
      return [];
    }

    const codeLenses: vscode.CodeLens[] = [];
    const text = document.getText();
    const lines = text.split("\n");

    const funcDefRegex = /^(?:\s*)(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(/;

    for (let i = 0; i < lines.length; i++) {
      const match = funcDefRegex.exec(lines[i]);
      if (match) {
        const funcName = match[1];
        if (fileFuncMap.has(funcName)) {
          const touchedTables = fileFuncMap.get(funcName)!;
          const range = new vscode.Range(i, 0, i, lines[i].length);

          const tablesSummary = touchedTables.slice(0, 3).join(", ");
          const more =
            touchedTables.length > 3
              ? ` +${touchedTables.length - 3} more`
              : "";

          const title = `⚡ SystemLens: Touches ${touchedTables.length} table${
            touchedTables.length === 1 ? "" : "s"
          } (${tablesSummary}${more}) — View Blast Radius`;

          const primaryTable = touchedTables[0];
          const command: vscode.Command = {
            title,
            command: "systemlens.analyzeTable",
            arguments: [primaryTable],
            tooltip: `Click to view blast radius for '${primaryTable}'`,
          };

          codeLenses.push(new vscode.CodeLens(range, command));
        }
      }
    }

    return codeLenses;
  }
}
