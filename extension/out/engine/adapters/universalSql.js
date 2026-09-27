"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.UniversalSqlAdapter = void 0;
exports.extractTablesFromSqlString = extractTablesFromSqlString;
const models_1 = require("../graph/models");
/**
 * Extracts table names from standard SQL strings using robust regex heuristics.
 */
function extractTablesFromSqlString(sql) {
    const tables = new Set();
    // Patterns for FROM, JOIN, INTO, UPDATE
    const fromJoinRegex = /\b(?:FROM|JOIN|INTO|UPDATE)\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)/gi;
    let match;
    while ((match = fromJoinRegex.exec(sql)) !== null) {
        const raw = match[1];
        const clean = raw.replace(/[`"']/g, "").split(".").pop() || raw;
        const lower = clean.toLowerCase();
        // Exclude common SQL keywords that can follow FROM/JOIN in subqueries
        if (!["select", "where", "values", "set", "order", "group", "having", "limit"].includes(lower)) {
            tables.add(lower);
        }
    }
    return Array.from(tables);
}
class UniversalSqlAdapter {
    languageId = "universal";
    supportedExtensions = [
        ".rs", ".cs", ".cpp", ".c", ".h", ".scala", ".kt", ".swift", ".dart", ".lua", ".r", ".sh"
    ];
    scanFile(filePath, content, knownTables) {
        const nodes = [];
        const edges = [];
        const fileNodeId = `file:${filePath}`;
        nodes.push({
            id: fileNodeId,
            type: "file",
            name: filePath,
            source_system: "universal",
        });
        const lines = content.split("\n");
        const sqlStringRegex = /["'`]([^"'`]*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)["'`]/gi;
        let match;
        let funcCounter = 0;
        while ((match = sqlStringRegex.exec(content)) !== null) {
            const sqlSnippet = match[1];
            const tables = extractTablesFromSqlString(sqlSnippet);
            if (tables.length > 0) {
                funcCounter++;
                const funcId = `func:${filePath}:query_${funcCounter}`;
                nodes.push({
                    id: funcId,
                    type: "function",
                    name: `query_${funcCounter}`,
                    source_system: "universal",
                    metadata: { file: filePath },
                });
                edges.push({
                    source: funcId,
                    target: fileNodeId,
                    type: "structural_belongs_to",
                    confidence: 1.0,
                    evidence: "belongs to",
                });
                for (const tbl of tables) {
                    edges.push({
                        source: funcId,
                        target: `table:${tbl}`,
                        type: "static_sql_string",
                        confidence: models_1.BASE_WEIGHTS.static_sql_string,
                        evidence: sqlSnippet.slice(0, 80),
                    });
                }
            }
        }
        return { nodes, edges };
    }
}
exports.UniversalSqlAdapter = UniversalSqlAdapter;
//# sourceMappingURL=universalSql.js.map