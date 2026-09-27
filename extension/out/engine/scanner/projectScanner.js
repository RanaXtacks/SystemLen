"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ProjectScanner = void 0;
const fs = require("fs");
const path = require("path");
const schemaDiscovery_1 = require("../schema/schemaDiscovery");
const graphBuilder_1 = require("../graph/graphBuilder");
const impactEngine_1 = require("../graph/impactEngine");
const universalSql_1 = require("../adapters/universalSql");
const python_1 = require("../adapters/python");
const javascript_1 = require("../adapters/javascript");
const golang_1 = require("../adapters/golang");
const java_1 = require("../adapters/java");
const ruby_1 = require("../adapters/ruby");
const php_1 = require("../adapters/php");
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
class ProjectScanner {
    workspaceRoot;
    adapters;
    universalAdapter;
    currentGraph = null;
    currentImpactEngine = null;
    fileCache = new Map();
    constructor(workspaceRoot) {
        this.workspaceRoot = workspaceRoot;
        this.universalAdapter = new universalSql_1.UniversalSqlAdapter();
        this.adapters = [
            new python_1.PythonCodeAdapter(),
            new javascript_1.JavaScriptCodeAdapter(),
            new golang_1.GolangCodeAdapter(),
            new java_1.JavaCodeAdapter(),
            new ruby_1.RubyCodeAdapter(),
            new php_1.PhpCodeAdapter(),
        ];
    }
    getGraph() {
        return this.currentGraph;
    }
    getImpactEngine() {
        return this.currentImpactEngine;
    }
    async scanProject(progress) {
        progress?.("starting", "SystemLens: Initializing auto-discovery...");
        // 1. Schema Discovery
        progress?.("scanning_schemas", "SystemLens: Discovering schemas and migrations...");
        const schemaEngine = new schemaDiscovery_1.SchemaDiscoveryEngine(this.workspaceRoot);
        const catalog = schemaEngine.discoverSchema();
        const knownTables = new Set(Object.keys(catalog.tables));
        // 2. Scan Code Files
        progress?.("scanning_code", "SystemLens: Scanning code dependencies...");
        const filesToScan = [];
        this.collectSourceFiles(this.workspaceRoot, filesToScan, 0);
        const builder = new graphBuilder_1.GraphBuilder();
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
            }
            catch (err) {
                console.warn(`[SystemLens] Error scanning ${relPath}:`, err);
            }
        }
        // 3. Build Graph
        progress?.("building_graph", "SystemLens: Assembling cross-layer graph...");
        this.currentGraph = builder.build();
        this.currentImpactEngine = new impactEngine_1.NativeImpactEngine(this.currentGraph);
        // Save to .systemlens/graph.json
        try {
            const systemlensDir = path.join(this.workspaceRoot, ".systemlens");
            if (!fs.existsSync(systemlensDir)) {
                fs.mkdirSync(systemlensDir, { recursive: true });
            }
            fs.writeFileSync(path.join(systemlensDir, "graph.json"), JSON.stringify(this.currentGraph, null, 2), "utf-8");
            // Also save to root graph.json if configured or present
            fs.writeFileSync(path.join(this.workspaceRoot, "graph.json"), JSON.stringify(this.currentGraph, null, 2), "utf-8");
        }
        catch (e) {
            console.warn("[SystemLens] Could not write graph cache file", e);
        }
        progress?.("completed", `SystemLens: Found ${Object.keys(catalog.tables).length} tables, ${this.currentGraph.metrics.total_nodes} nodes.`);
        return this.currentGraph;
    }
    updateFile(fullPath) {
        if (!this.currentGraph)
            return;
        const relPath = path.relative(this.workspaceRoot, fullPath).replace(/\\/g, "/");
        try {
            if (!fs.existsSync(fullPath)) {
                this.fileCache.delete(relPath);
            }
            else {
                const content = fs.readFileSync(fullPath, "utf-8");
                const adapter = this.getAdapterForFile(fullPath);
                const { nodes, edges } = adapter.scanFile(relPath, content);
                this.fileCache.set(relPath, { nodes, edges });
            }
            // Re-assemble
            this.rebuildFromCache();
        }
        catch (err) {
            console.warn(`[SystemLens] Incremental update failed for ${relPath}:`, err);
        }
    }
    rebuildFromCache() {
        const schemaEngine = new schemaDiscovery_1.SchemaDiscoveryEngine(this.workspaceRoot);
        const catalog = schemaEngine.discoverSchema();
        const builder = new graphBuilder_1.GraphBuilder();
        builder.addSchemaCatalog(catalog);
        for (const { nodes, edges } of this.fileCache.values()) {
            builder.addCodeAnalysis(nodes, edges);
        }
        this.currentGraph = builder.build();
        this.currentImpactEngine = new impactEngine_1.NativeImpactEngine(this.currentGraph);
    }
    getAdapterForFile(fullPath) {
        const ext = path.extname(fullPath).toLowerCase();
        for (const adapter of this.adapters) {
            if (adapter.supportedExtensions.includes(ext)) {
                return adapter;
            }
        }
        return this.universalAdapter;
    }
    collectSourceFiles(dir, results, depth) {
        if (depth > 8)
            return;
        let entries = [];
        try {
            entries = fs.readdirSync(dir, { withFileTypes: true });
        }
        catch {
            return;
        }
        for (const entry of entries) {
            const name = entry.name;
            if (DEFAULT_IGNORED_DIRS.has(name) || name.startsWith("."))
                continue;
            const fullPath = path.join(dir, name);
            if (entry.isDirectory()) {
                this.collectSourceFiles(fullPath, results, depth + 1);
            }
            else if (entry.isFile()) {
                const ext = path.extname(name).toLowerCase();
                // Check if supported by any adapter
                if (this.adapters.some(a => a.supportedExtensions.includes(ext)) ||
                    this.universalAdapter.supportedExtensions.includes(ext)) {
                    results.push(fullPath);
                }
            }
        }
    }
}
exports.ProjectScanner = ProjectScanner;
//# sourceMappingURL=projectScanner.js.map