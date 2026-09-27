import * as fs from "fs";
import * as path from "path";
import { SchemaDiscoveryEngine } from "../schema/schemaDiscovery";
import { GraphBuilder } from "../graph/graphBuilder";
import { GraphData, Node, Edge } from "../graph/models";
import { NativeImpactEngine } from "../graph/impactEngine";
import { CodeAdapter } from "../adapters/base";
import { UniversalSqlAdapter } from "../adapters/universalSql";
import { PythonCodeAdapter } from "../adapters/python";
import { JavaScriptCodeAdapter } from "../adapters/javascript";
import { GolangCodeAdapter } from "../adapters/golang";
import { JavaCodeAdapter } from "../adapters/java";
import { RubyCodeAdapter } from "../adapters/ruby";
import { PhpCodeAdapter } from "../adapters/php";

const DEFAULT_IGNORED_DIRS = new Set([
  "node_modules",
  ".git",
  ".venv",
  "venv",
  "__pycache__",
  "dist",
  "build",
  "target",
  "vendor",
  ".systemlens",
  ".agents",
  ".gemini",
  ".idea",
  ".vscode",
]);

export interface ScanProgressCallback {
  (status: "starting" | "scanning_schemas" | "scanning_code" | "building_graph" | "completed", message: string): void;
}

export class ProjectScanner {
  private adapters: CodeAdapter[];
  private universalAdapter: UniversalSqlAdapter;
  private currentGraph: GraphData | null = null;
  private currentImpactEngine: NativeImpactEngine | null = null;
  private fileCache = new Map<string, { nodes: Node[]; edges: Edge[] }>();

  constructor(private workspaceRoot: string) {
    this.universalAdapter = new UniversalSqlAdapter();
    this.adapters = [
      new PythonCodeAdapter(),
      new JavaScriptCodeAdapter(),
      new GolangCodeAdapter(),
      new JavaCodeAdapter(),
      new RubyCodeAdapter(),
      new PhpCodeAdapter(),
    ];
  }

  public getGraph(): GraphData | null {
    return this.currentGraph;
  }

  public getImpactEngine(): NativeImpactEngine | null {
    return this.currentImpactEngine;
  }

  public async scanProject(progress?: ScanProgressCallback): Promise<GraphData> {
    progress?.("starting", "SystemLens: Initializing auto-discovery...");

    // 1. Schema Discovery
    progress?.("scanning_schemas", "SystemLens: Discovering schemas and migrations...");
    const schemaEngine = new SchemaDiscoveryEngine(this.workspaceRoot);
    const catalog = schemaEngine.discoverSchema();

    const knownTables = new Set<string>(Object.keys(catalog.tables));

    // 2. Scan Code Files
    progress?.("scanning_code", "SystemLens: Scanning code dependencies...");
    const filesToScan: string[] = [];
    this.collectSourceFiles(this.workspaceRoot, filesToScan, 0);

    const builder = new GraphBuilder();
    builder.addSchemaCatalog(catalog);

    this.fileCache.clear();

    for (const fullPath of filesToScan) {
      const relPath = path.relative(this.workspaceRoot, fullPath).replace(/\\/g, "/");
      try {
        const content = fs.readFileSync(fullPath, "utf-8");
        const adapter = this.getAdapterForFile(fullPath);
        const { nodes, edges } = adapter.scanFile(relPath, content, knownTables);
        this.fileCache.set(relPath, { nodes, edges });
        builder.addCodeAnalysis(nodes, edges);
      } catch (err) {
        console.warn(`[SystemLens] Error scanning ${relPath}:`, err);
      }
    }

    // 3. Build Graph
    progress?.("building_graph", "SystemLens: Assembling cross-layer graph...");
    this.currentGraph = builder.build();
    this.currentImpactEngine = new NativeImpactEngine(this.currentGraph);

    // Save to .systemlens/graph.json
    try {
      const systemlensDir = path.join(this.workspaceRoot, ".systemlens");
      if (!fs.existsSync(systemlensDir)) {
        fs.mkdirSync(systemlensDir, { recursive: true });
      }
      fs.writeFileSync(
        path.join(systemlensDir, "graph.json"),
        JSON.stringify(this.currentGraph, null, 2),
        "utf-8"
      );
      // Also save to root graph.json if configured or present
      fs.writeFileSync(
        path.join(this.workspaceRoot, "graph.json"),
        JSON.stringify(this.currentGraph, null, 2),
        "utf-8"
      );
    } catch (e) {
      console.warn("[SystemLens] Could not write graph cache file", e);
    }

    progress?.("completed", `SystemLens: Found ${Object.keys(catalog.tables).length} tables, ${this.currentGraph.metrics.total_nodes} nodes.`);
    return this.currentGraph;
  }

  public updateFile(fullPath: string): void {
    if (!this.currentGraph) return;

    const relPath = path.relative(this.workspaceRoot, fullPath).replace(/\\/g, "/");
    try {
      if (!fs.existsSync(fullPath)) {
        this.fileCache.delete(relPath);
      } else {
        const content = fs.readFileSync(fullPath, "utf-8");
        const adapter = this.getAdapterForFile(fullPath);
        const { nodes, edges } = adapter.scanFile(relPath, content);
        this.fileCache.set(relPath, { nodes, edges });
      }

      // Re-assemble
      this.rebuildFromCache();
    } catch (err) {
      console.warn(`[SystemLens] Incremental update failed for ${relPath}:`, err);
    }
  }

  private rebuildFromCache(): void {
    const schemaEngine = new SchemaDiscoveryEngine(this.workspaceRoot);
    const catalog = schemaEngine.discoverSchema();

    const builder = new GraphBuilder();
    builder.addSchemaCatalog(catalog);

    for (const { nodes, edges } of this.fileCache.values()) {
      builder.addCodeAnalysis(nodes, edges);
    }

    this.currentGraph = builder.build();
    this.currentImpactEngine = new NativeImpactEngine(this.currentGraph);
  }

  private getAdapterForFile(fullPath: string): CodeAdapter {
    const ext = path.extname(fullPath).toLowerCase();
    for (const adapter of this.adapters) {
      if (adapter.supportedExtensions.includes(ext)) {
        return adapter;
      }
    }
    return this.universalAdapter;
  }

  private collectSourceFiles(dir: string, results: string[], depth: number): void {
    if (depth > 8) return;

    let entries: fs.Dirent[] = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      const name = entry.name;
      if (DEFAULT_IGNORED_DIRS.has(name) || name.startsWith(".")) continue;

      const fullPath = path.join(dir, name);

      if (entry.isDirectory()) {
        this.collectSourceFiles(fullPath, results, depth + 1);
      } else if (entry.isFile()) {
        const ext = path.extname(name).toLowerCase();
        // Check if supported by any adapter
        if (
          this.adapters.some(a => a.supportedExtensions.includes(ext)) ||
          this.universalAdapter.supportedExtensions.includes(ext)
        ) {
          results.push(fullPath);
        }
      }
    }
  }
}
