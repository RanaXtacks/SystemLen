"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JavaScriptCodeAdapter = void 0;
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
class JavaScriptCodeAdapter {
    languageId = "javascript";
    supportedExtensions = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"];
    scanFile(filePath, content, knownTables) {
        const nodes = [];
        const edges = [];
        const fileNodeId = `file:${filePath}`;
        nodes.push({
            id: fileNodeId,
            type: "file",
            name: filePath,
            source_system: "javascript",
        });
        const lines = content.split("\n");
        const funcPatterns = [
            /^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(/,
            /^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>/,
            /^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s+)?function\b/,
            /^\s*(?:async\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*\{/,
        ];
        const functions = [];
        let currentFunc = null;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            let matchedName = null;
            for (const pattern of funcPatterns) {
                const m = pattern.exec(line);
                if (m) {
                    const name = m[1];
                    if (!["if", "for", "while", "switch", "catch", "return"].includes(name)) {
                        matchedName = name;
                        break;
                    }
                }
            }
            if (matchedName) {
                if (currentFunc) {
                    functions.push({
                        name: currentFunc.name,
                        id: currentFunc.id,
                        startLine: currentFunc.startLine,
                        body: currentFunc.lines.join("\n"),
                    });
                }
                currentFunc = {
                    name: matchedName,
                    id: `func:${filePath}:${matchedName}`,
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
                name: "<module>",
                id: `func:${filePath}:<module>`,
                startLine: 1,
                body: content,
            });
        }
        for (const fn of functions) {
            nodes.push({
                id: fn.id,
                type: "function",
                name: fn.name,
                source_system: "javascript",
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
            // 1. Prisma Client: prisma.user.findMany(...)
            const prismaRegex = /\bprisma\.([a-zA-Z0-9_]+)\.(?:findMany|findUnique|findFirst|create|update|delete|upsert|count)\s*\(/g;
            let pMatch;
            while ((pMatch = prismaRegex.exec(body)) !== null) {
                const model = pMatch[1];
                const tbl = pluralize(model);
                edges.push({
                    source: fn.id,
                    target: `table:${tbl}`,
                    type: "orm_call",
                    confidence: models_1.BASE_WEIGHTS.orm_call,
                    evidence: pMatch[0],
                    metadata: { file: filePath, framework: "prisma" },
                });
            }
            // 2. Knex: knex('users')
            const knexRegex = /\bknex\s*\(\s*['"]([a-zA-Z0-9_]+)['"]\s*\)/g;
            let kMatch;
            while ((kMatch = knexRegex.exec(body)) !== null) {
                const tbl = kMatch[1].toLowerCase();
                edges.push({
                    source: fn.id,
                    target: `table:${tbl}`,
                    type: "orm_call",
                    confidence: models_1.BASE_WEIGHTS.orm_call,
                    evidence: kMatch[0],
                    metadata: { file: filePath, framework: "knex" },
                });
            }
            // 3. Sequelize: User.findAll(...)
            const seqRegex = /\b([A-Z][a-zA-Z0-9_]+)\.(?:findAll|findOne|findByPk|create|update|destroy|count)\s*\(/g;
            let sMatch;
            while ((sMatch = seqRegex.exec(body)) !== null) {
                const model = sMatch[1];
                if (!["Promise", "Object", "Array", "JSON", "Math", "Date", "String", "Number"].includes(model)) {
                    const tbl = pluralize(model);
                    edges.push({
                        source: fn.id,
                        target: `table:${tbl}`,
                        type: "orm_call",
                        confidence: models_1.BASE_WEIGHTS.orm_call,
                        evidence: sMatch[0],
                        metadata: { file: filePath, framework: "sequelize" },
                    });
                }
            }
            // 4. Raw SQL: query("SELECT ...") or template literals `SELECT ...`
            const rawSqlRegex = /[`'"]([^`'"]*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)[`'"]/gi;
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
            // 5. Dynamic SQL: client.query(varName)
            const dynamicRegex = /\b(?:query|execute|raw)\s*\(\s*([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[,)]/g;
            let dynMatch;
            while ((dynMatch = dynamicRegex.exec(body)) !== null) {
                const varName = dynMatch[1];
                if (!varName.startsWith('"') && !varName.startsWith("'") && !varName.startsWith("`")) {
                    edges.push({
                        source: fn.id,
                        target: "table:unresolved",
                        type: "dynamic_unresolved",
                        confidence: models_1.BASE_WEIGHTS.dynamic_unresolved,
                        evidence: dynMatch[0],
                    });
                }
            }
        }
        return { nodes, edges };
    }
}
exports.JavaScriptCodeAdapter = JavaScriptCodeAdapter;
//# sourceMappingURL=javascript.js.map