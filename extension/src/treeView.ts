import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

export interface GraphData {
  nodes?: any[];
  edges?: any[];
  metrics?: any;
}

export class TreeNode extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly contextValue?: string,
    public readonly children?: TreeNode[],
    public readonly command?: vscode.Command
  ) {
    super(label, collapsibleState);
  }
}

export class SystemLensTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private _onDidChangeTreeData: vscode.EventEmitter<TreeNode | undefined | void> =
    new vscode.EventEmitter<TreeNode | undefined | void>();
  readonly onDidChangeTreeData: vscode.Event<TreeNode | undefined | void> =
    this._onDidChangeTreeData.event;

  private graphData: GraphData | null = null;
  private graphPath: string | null = null;

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
      this.graphPath = candidate;
      try {
        const raw = fs.readFileSync(candidate, "utf-8");
        this.graphData = JSON.parse(raw);
      } catch (err) {
        console.error("SystemLens: Failed to parse graph file", err);
        this.graphData = null;
      }
    } else {
      this.graphData = null;
      this.graphPath = null;
    }
  }

  public setGraphData(graph: GraphData | null): void {
    this.graphData = graph;
    this._onDidChangeTreeData.fire();
  }

  public refresh(graph?: GraphData | null): void {
    if (graph !== undefined) {
      this.graphData = graph;
    } else {
      this.reloadGraph();
    }
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeNode): Thenable<TreeNode[]> {
    if (!this.graphData || !this.graphData.nodes || this.graphData.nodes.length === 0) {
      const rescanNode = new TreeNode(
        "No database dependencies indexed yet (Click to Rescan)",
        vscode.TreeItemCollapsibleState.None,
        "action",
        undefined,
        {
          command: "systemlens.rescanProject",
          title: "Rescan Workspace",
        }
      );
      rescanNode.iconPath = new vscode.ThemeIcon("sync");
      return Promise.resolve([rescanNode]);
    }

    if (!element) {
      // Root items
      return Promise.resolve(this.getRootItems());
    }

    if (element.children) {
      return Promise.resolve(element.children);
    }

    return Promise.resolve([]);
  }

  private getRootItems(): TreeNode[] {
    const nodes = this.graphData?.nodes || [];
    const edges = this.graphData?.edges || [];

    const tables = nodes.filter(
      (n: any) =>
        (n.type === "table" || n.type === "view") &&
        n.name !== "<unresolved_dynamic_query>"
    );

    // 1. Tables Section
    const tableNodes: TreeNode[] = tables.map((t: any) => {
      const tName = t.name || t.id.replace("table:", "");

      // Find functions touching this table
      const touchingFuncEdges = edges.filter(
        (e: any) =>
          e.target === t.id ||
          e.target?.toLowerCase() === `table:${tName.toLowerCase()}` ||
          e.target?.toLowerCase() === `table:public.${tName.toLowerCase()}`
      );

      const childItems: TreeNode[] = [];

      // Action button to run impact
      const analyzeAction = new TreeNode(
        `🔍 Analyze Blast Radius for '${tName}'`,
        vscode.TreeItemCollapsibleState.None,
        "action",
        undefined,
        {
          command: "systemlens.analyzeTable",
          title: "Analyze Table",
          arguments: [tName],
        }
      );
      analyzeAction.iconPath = new vscode.ThemeIcon("search");
      childItems.push(analyzeAction);

      // Functions sub-list
      if (touchingFuncEdges.length > 0) {
        const funcItems: TreeNode[] = touchingFuncEdges.map((e: any) => {
          const srcNode = nodes.find((n: any) => n.id === e.source);
          const fName = srcNode?.name || e.source.split(":").pop();
          const conf = Math.round((e.confidence || 0.8) * 100);
          const item = new TreeNode(
            `⚡ ${fName} (${conf}% conf)`,
            vscode.TreeItemCollapsibleState.None
          );
          item.tooltip = `Type: ${e.type} | Evidence: ${e.evidence || "Direct reference"}`;
          item.iconPath = new vscode.ThemeIcon("symbol-function");
          return item;
        });

        const funcsGroup = new TreeNode(
          `Functions (${touchingFuncEdges.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          "func_group",
          funcItems
        );
        funcsGroup.iconPath = new vscode.ThemeIcon("code");
        childItems.push(funcsGroup);
      }

      // Foreign keys / downstream tables
      const fkEdges = edges.filter(
        (e: any) =>
          (e.type === "declared_fk" || e.type === "inferred_naming") &&
          (e.target === t.id || e.target?.endsWith(`.${tName}`))
      );
      if (fkEdges.length > 0) {
        const fkItems: TreeNode[] = fkEdges.map((e: any) => {
          const srcTable = e.source.replace("table:", "").split(".").pop();
          const item = new TreeNode(
            `🗄️ ${srcTable} (FK)`,
            vscode.TreeItemCollapsibleState.None
          );
          item.iconPath = new vscode.ThemeIcon("database");
          return item;
        });
        const fkGroup = new TreeNode(
          `Referenced By (${fkEdges.length})`,
          vscode.TreeItemCollapsibleState.Collapsed,
          "fk_group",
          fkItems
        );
        fkGroup.iconPath = new vscode.ThemeIcon("references");
        childItems.push(fkGroup);
      }

      const tableItem = new TreeNode(
        `🗄️ ${tName} (${touchingFuncEdges.length + fkEdges.length} dependents)`,
        vscode.TreeItemCollapsibleState.Collapsed,
        "table",
        childItems
      );
      tableItem.iconPath = new vscode.ThemeIcon("database");
      return tableItem;
    });

    const tablesSection = new TreeNode(
      `📊 Tables (${tables.length})`,
      vscode.TreeItemCollapsibleState.Expanded,
      "tables_section",
      tableNodes
    );
    tablesSection.iconPath = new vscode.ThemeIcon("table");

    // 2. Blind Spots Section
    const dynamicEdges = edges.filter(
      (e: any) => e.type === "dynamic_unresolved"
    );
    const blindSpotItems: TreeNode[] = [
      new TreeNode(
        `Dynamic SQL: ${dynamicEdges.length} unresolved calls`,
        vscode.TreeItemCollapsibleState.None
      ),
      new TreeNode(
        "Cross-service boundaries: Not analyzed (V1)",
        vscode.TreeItemCollapsibleState.None
      ),
    ];
    blindSpotItems[0].iconPath = new vscode.ThemeIcon("warning");
    blindSpotItems[1].iconPath = new vscode.ThemeIcon("info");

    const blindSpotsSection = new TreeNode(
      `⚠️ Blind Spots (${dynamicEdges.length > 0 ? "Honesty Active" : "Clean"})`,
      vscode.TreeItemCollapsibleState.Collapsed,
      "blind_spots_section",
      blindSpotItems
    );
    blindSpotsSection.iconPath = new vscode.ThemeIcon("shield");

    // 3. Stats Section
    const statsItems: TreeNode[] = [
      new TreeNode(`Total Nodes: ${nodes.length}`, vscode.TreeItemCollapsibleState.None),
      new TreeNode(`Total Edges: ${edges.length}`, vscode.TreeItemCollapsibleState.None),
      new TreeNode(
        `Dynamic Query Ratio: ${
          edges.length > 0
            ? ((dynamicEdges.length / edges.length) * 100).toFixed(1) + "%"
            : "0%"
        }`,
        vscode.TreeItemCollapsibleState.None
      ),
    ];
    statsItems.forEach((s) => (s.iconPath = new vscode.ThemeIcon("graph")));

    const statsSection = new TreeNode(
      "📈 Graph Stats",
      vscode.TreeItemCollapsibleState.Collapsed,
      "stats_section",
      statsItems
    );
    statsSection.iconPath = new vscode.ThemeIcon("dashboard");

    return [tablesSection, blindSpotsSection, statsSection];
  }
}
