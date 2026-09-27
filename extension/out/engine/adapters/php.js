"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PhpCodeAdapter = void 0;
const models_1 = require("../graph/models");
const universalSql_1 = require("./universalSql");
function pluralize(word) {
    const lower = word.toLowerCase();
    if (lower.endsWith("y") && !/[aeiou]y$/.test(lower))
        return lower.slice(0, -1) + "ies";
    if (lower.endsWith("s") || lower.endsWith("sh") || lower.endsWith("ch") || lower.endsWith("x"))
        return lower + "es";
    return lower + "s";
}
class PhpCodeAdapter {
    languageId = "php";
    supportedExtensions = [".php"];
    scanFile(filePath, content, knownTables) {
        const nodes = [];
        const edges = [];
        const fileNodeId = `file:${filePath}`;
        nodes.push({
            id: fileNodeId,
            type: "file",
            name: filePath,
            source_system: "php",
        });
        const lines = content.split("\n");
        const funcRegex = /^\s*(?:public|protected|private)?\s*(?:static\s+)?function\s+([a-zA-Z0-9_]+)\s*\(/;
        const functions = [];
        let currentFunc = null;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const match = funcRegex.exec(line);
            if (match) {
                if (currentFunc) {
                    functions.push({
                        name: currentFunc.name,
                        id: currentFunc.id,
                        startLine: currentFunc.startLine,
                        body: currentFunc.lines.join("\n"),
                    });
                }
                const fnName = match[1];
                currentFunc = {
                    name: fnName,
                    id: `func:${filePath}:${fnName}`,
                    startLine: i + 1,
                    lines: [line],
                };
            }
            else if (currentFunc) {
                currentFunc.lines.push(line);
            }
        }
        if (currentFunc) {
            functions.push({
                name: currentFunc.name,
                id: currentFunc.id,
                startLine: currentFunc.startLine,
                body: currentFunc.lines.join("\n"),
            });
        }
        if (functions.length === 0) {
            functions.push({
                name: "<file>",
                id: `func:${filePath}:<file>`,
                startLine: 1,
                body: content,
            });
        }
        for (const fn of functions) {
            nodes.push({
                id: fn.id,
                type: "function",
                name: fn.name,
                source_system: "php",
                metadata: { file: filePath, lineno: fn.startLine },
            });
            edges.push({
                source: fn.id,
                target: fileNodeId,
                type: "structural_belongs_to",
                confidence: 1.0,
                evidence: `in ${filePath}:${fn.startLine}`,
            });
            const body = fn.body;
            // 1. Laravel DB::table('users')
            const dbTableRegex = /\bDB::table\s*\(\s*["']([a-zA-Z0-9_]+)["']\s*\)/g;
            let dbMatch;
            while ((dbMatch = dbTableRegex.exec(body)) !== null) {
                const tbl = dbMatch[1].toLowerCase();
                edges.push({
                    source: fn.id,
                    target: `table:${tbl}`,
                    type: "orm_call",
                    confidence: models_1.BASE_WEIGHTS.orm_call,
                    evidence: dbMatch[0],
                    metadata: { framework: "laravel" },
                });
            }
            // 2. Laravel Eloquent: Model::where(...) / Model::find(...)
            const eloquentRegex = /\b([A-Z][a-zA-Z0-9_]*)::(?:where|find|findOrFail|create|update|all|query|first)\s*\(/g;
            let elMatch;
            while ((elMatch = eloquentRegex.exec(body)) !== null) {
                const model = elMatch[1];
                if (!["DB", "Route", "Schema", "Auth", "Gate", "Validator", "Response", "Request", "App", "Config"].includes(model)) {
                    const tbl = pluralize(model);
                    edges.push({
                        source: fn.id,
                        target: `table:${tbl}`,
                        type: "orm_call",
                        confidence: models_1.BASE_WEIGHTS.orm_call,
                        evidence: elMatch[0],
                        metadata: { framework: "eloquent", model },
                    });
                }
            }
            // 3. Raw SQL in strings: DB::select("SELECT ...") or $pdo->query("SELECT ...")
            const rawSqlRegex = /["']([^"']*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)["']/gi;
            let sqlMatch;
            while ((sqlMatch = rawSqlRegex.exec(body)) !== null) {
                const snippet = sqlMatch[1];
                const tables = (0, universalSql_1.extractTablesFromSqlString)(snippet);
                for (const tbl of tables) {
                    edges.push({
                        source: fn.id,
                        target: `table:${tbl}`,
                        type: "static_sql_string",
                        confidence: models_1.BASE_WEIGHTS.static_sql_string,
                        evidence: snippet.slice(0, 80),
                    });
                }
            }
        }
        return { nodes, edges };
    }
}
exports.PhpCodeAdapter = PhpCodeAdapter;
//# sourceMappingURL=php.js.map