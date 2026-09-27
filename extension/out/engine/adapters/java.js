"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.JavaCodeAdapter = void 0;
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
class JavaCodeAdapter {
    languageId = "java";
    supportedExtensions = [".java", ".kt"];
    scanFile(filePath, content, knownTables) {
        const nodes = [];
        const edges = [];
        const fileNodeId = `file:${filePath}`;
        nodes.push({
            id: fileNodeId,
            type: "file",
            name: filePath,
            source_system: "java",
        });
        const lines = content.split("\n");
        // 1. Check for Spring Data Repository interface: public interface UserRepository extends JpaRepository<User, Long>
        const repoMatch = /interface\s+([a-zA-Z0-9_]+)\s+extends\s+(?:JpaRepository|CrudRepository|PagingAndSortingRepository)\s*<\s*([a-zA-Z0-9_]+)/.exec(content);
        if (repoMatch) {
            const entityName = repoMatch[2];
            const tbl = pluralize(entityName);
            const repoName = repoMatch[1];
            const funcId = `func:${filePath}:${repoName}`;
            nodes.push({
                id: funcId,
                type: "function",
                name: repoName,
                source_system: "java",
                metadata: { file: filePath, entity: entityName },
            });
            edges.push({
                source: funcId,
                target: fileNodeId,
                type: "structural_belongs_to",
                confidence: 1.0,
                evidence: "repository interface",
            });
            edges.push({
                source: funcId,
                target: `table:${tbl}`,
                type: "orm_call",
                confidence: models_1.BASE_WEIGHTS.orm_call,
                evidence: repoMatch[0],
            });
        }
        // 2. Scan methods and queries
        const methodRegex = /^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?[\w<>\[\]\?]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{/;
        const functions = [];
        let currentFunc = null;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const match = methodRegex.exec(line);
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
                name: "<class>",
                id: `func:${filePath}:<class>`,
                startLine: 1,
                body: content,
            });
        }
        for (const fn of functions) {
            if (!nodes.some(n => n.id === fn.id)) {
                nodes.push({
                    id: fn.id,
                    type: "function",
                    name: fn.name,
                    source_system: "java",
                    metadata: { file: filePath, lineno: fn.startLine },
                });
                edges.push({
                    source: fn.id,
                    target: fileNodeId,
                    type: "structural_belongs_to",
                    confidence: 1.0,
                    evidence: `in ${filePath}:${fn.startLine}`,
                });
            }
            const body = fn.body;
            // 3. Spring @Query annotation: @Query("SELECT u FROM User u ...") or nativeQuery = true
            const queryAnnotationRegex = /@Query\s*\(\s*(?:value\s*=\s*)?["']([^"']+)["']/g;
            let qMatch;
            while ((qMatch = queryAnnotationRegex.exec(body)) !== null) {
                const queryText = qMatch[1];
                const tables = (0, universalSql_1.extractTablesFromSqlString)(queryText);
                for (const tbl of tables) {
                    edges.push({
                        source: fn.id,
                        target: `table:${tbl}`,
                        type: "static_sql_string",
                        confidence: models_1.BASE_WEIGHTS.static_sql_string,
                        evidence: queryText.slice(0, 80),
                    });
                }
            }
            // 4. Raw SQL strings in methods
            const rawSqlRegex = /"([^"]*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)"/gi;
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
exports.JavaCodeAdapter = JavaCodeAdapter;
//# sourceMappingURL=java.js.map