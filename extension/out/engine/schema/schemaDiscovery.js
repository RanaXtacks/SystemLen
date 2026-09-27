"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SchemaDiscoveryEngine = void 0;
const fs = require("fs");
const path = require("path");
const sqlParser_1 = require("./sqlParser");
const prismaParser_1 = require("./prismaParser");
const activeRecordParser_1 = require("./activeRecordParser");
const IGNORED_DIRS = new Set([
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".systemlens",
    ".agents",
    ".gemini",
]);
/**
 * Recursively discovers and parses schema definitions across a workspace.
 */
class SchemaDiscoveryEngine {
    workspaceRoot;
    constructor(workspaceRoot) {
        this.workspaceRoot = workspaceRoot;
    }
    discoverSchema() {
        const unifiedCatalog = {
            sourceType: "auto_discovery",
            tables: {},
        };
        const filesToParse = [];
        this.scanDirectory(this.workspaceRoot, filesToParse, 0);
        // 1. Parse Prisma schemas
        for (const f of filesToParse.filter(f => f.type === "prisma")) {
            try {
                const text = fs.readFileSync(f.path, "utf-8");
                const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
                const cat = (0, prismaParser_1.parsePrismaSchema)(text, rel);
                this.mergeCatalog(unifiedCatalog, cat);
            }
            catch (err) {
                console.warn(`[SystemLens] Failed to parse Prisma schema: ${f.path}`, err);
            }
        }
        // 2. Parse Rails schemas
        for (const f of filesToParse.filter(f => f.type === "rails")) {
            try {
                const text = fs.readFileSync(f.path, "utf-8");
                const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
                const cat = (0, activeRecordParser_1.parseActiveRecordSchema)(text, rel);
                this.mergeCatalog(unifiedCatalog, cat);
            }
            catch (err) {
                console.warn(`[SystemLens] Failed to parse Rails schema: ${f.path}`, err);
            }
        }
        // 3. Parse SQL migration/DDL files
        for (const f of filesToParse.filter(f => f.type === "sql")) {
            try {
                const text = fs.readFileSync(f.path, "utf-8");
                const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
                const cat = (0, sqlParser_1.parseSqlDdl)(text, rel);
                this.mergeCatalog(unifiedCatalog, cat);
            }
            catch (err) {
                console.warn(`[SystemLens] Failed to parse SQL schema: ${f.path}`, err);
            }
        }
        return unifiedCatalog;
    }
    scanDirectory(dir, results, depth) {
        if (depth > 6)
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
            if (IGNORED_DIRS.has(name) || name.startsWith("."))
                continue;
            const fullPath = path.join(dir, name);
            if (entry.isDirectory()) {
                this.scanDirectory(fullPath, results, depth + 1);
            }
            else if (entry.isFile()) {
                const lower = name.toLowerCase();
                if (lower.endsWith(".sql")) {
                    results.push({ path: fullPath, type: "sql" });
                }
                else if (lower.endsWith(".prisma") || lower === "schema.prisma") {
                    results.push({ path: fullPath, type: "prisma" });
                }
                else if (lower === "schema.rb") {
                    results.push({ path: fullPath, type: "rails" });
                }
            }
        }
    }
    mergeCatalog(dest, src) {
        for (const [tableKey, srcTable] of Object.entries(src.tables)) {
            if (!dest.tables[tableKey]) {
                dest.tables[tableKey] = srcTable;
            }
            else {
                // Merge columns
                const existingColNames = new Set(dest.tables[tableKey].columns.map(c => c.name));
                for (const col of srcTable.columns) {
                    if (!existingColNames.has(col.name)) {
                        dest.tables[tableKey].columns.push(col);
                    }
                }
                // Merge foreign keys
                const existingFkTargets = new Set(dest.tables[tableKey].foreignKeys.map(fk => fk.targetTable));
                for (const fk of srcTable.foreignKeys) {
                    if (!existingFkTargets.has(fk.targetTable)) {
                        dest.tables[tableKey].foreignKeys.push(fk);
                    }
                }
            }
        }
    }
}
exports.SchemaDiscoveryEngine = SchemaDiscoveryEngine;
//# sourceMappingURL=schemaDiscovery.js.map