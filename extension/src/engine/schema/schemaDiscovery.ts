import * as fs from "fs";
import * as path from "path";
import { SchemaCatalog, TableDefinition } from "./types";
import { parseSqlDdl } from "./sqlParser";
import { parsePrismaSchema } from "./prismaParser";
import { parseActiveRecordSchema } from "./activeRecordParser";

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
export class SchemaDiscoveryEngine {
  constructor(private workspaceRoot: string) {}

  public discoverSchema(): SchemaCatalog {
    const unifiedCatalog: SchemaCatalog = {
      sourceType: "auto_discovery",
      tables: {},
    };

    const filesToParse: { path: string; type: "sql" | "prisma" | "rails" }[] = [];
    this.scanDirectory(this.workspaceRoot, filesToParse, 0);

    // 1. Parse Prisma schemas
    for (const f of filesToParse.filter(f => f.type === "prisma")) {
      try {
        const text = fs.readFileSync(f.path, "utf-8");
        const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
        const cat = parsePrismaSchema(text, rel);
        this.mergeCatalog(unifiedCatalog, cat);
      } catch (err) {
        console.warn(`[SystemLens] Failed to parse Prisma schema: ${f.path}`, err);
      }
    }

    // 2. Parse Rails schemas
    for (const f of filesToParse.filter(f => f.type === "rails")) {
      try {
        const text = fs.readFileSync(f.path, "utf-8");
        const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
        const cat = parseActiveRecordSchema(text, rel);
        this.mergeCatalog(unifiedCatalog, cat);
      } catch (err) {
        console.warn(`[SystemLens] Failed to parse Rails schema: ${f.path}`, err);
      }
    }

    // 3. Parse SQL migration/DDL files
    for (const f of filesToParse.filter(f => f.type === "sql")) {
      try {
        const text = fs.readFileSync(f.path, "utf-8");
        const rel = path.relative(this.workspaceRoot, f.path).replace(/\\/g, "/");
        const cat = parseSqlDdl(text, rel);
        this.mergeCatalog(unifiedCatalog, cat);
      } catch (err) {
        console.warn(`[SystemLens] Failed to parse SQL schema: ${f.path}`, err);
      }
    }

    return unifiedCatalog;
  }

  private scanDirectory(
    dir: string,
    results: { path: string; type: "sql" | "prisma" | "rails" }[],
    depth: number
  ): void {
    if (depth > 6) return;

    let entries: fs.Dirent[] = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      const name = entry.name;
      if (IGNORED_DIRS.has(name) || name.startsWith(".")) continue;

      const fullPath = path.join(dir, name);

      if (entry.isDirectory()) {
        this.scanDirectory(fullPath, results, depth + 1);
      } else if (entry.isFile()) {
        const lower = name.toLowerCase();
        if (lower.endsWith(".sql")) {
          results.push({ path: fullPath, type: "sql" });
        } else if (lower.endsWith(".prisma") || lower === "schema.prisma") {
          results.push({ path: fullPath, type: "prisma" });
        } else if (lower === "schema.rb") {
          results.push({ path: fullPath, type: "rails" });
        }
      }
    }
  }

  private mergeCatalog(dest: SchemaCatalog, src: SchemaCatalog): void {
    for (const [tableKey, srcTable] of Object.entries(src.tables)) {
      if (!dest.tables[tableKey]) {
        dest.tables[tableKey] = srcTable;
      } else {
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
