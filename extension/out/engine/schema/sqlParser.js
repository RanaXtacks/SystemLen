"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.parseSqlDdl = parseSqlDdl;
/**
 * Strips SQL comments and string literals to prepare SQL for DDL parsing.
 */
function stripComments(sql) {
    // Remove block comments /* ... */
    let cleaned = sql.replace(/\/\*[\s\S]*?\*\//g, "");
    // Remove single line comments -- ...
    cleaned = cleaned.replace(/--.*$/gm, "");
    return cleaned;
}
/**
 * Parses raw SQL migration / DDL text and extracts tables, views, and foreign keys.
 */
function parseSqlDdl(sqlText, sourceFile) {
    const catalog = {
        sourceType: "sql_ddl",
        tables: {},
    };
    const sql = stripComments(sqlText);
    // 1. Match CREATE TABLE statements with paren-depth tracking for nested parens
    const createTableHeadRegex = /CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s*\(/gi;
    let match;
    while ((match = createTableHeadRegex.exec(sql)) !== null) {
        const rawTableName = match[1];
        const startIndex = createTableHeadRegex.lastIndex; // index right after '('
        let depth = 1;
        let endIndex = startIndex;
        while (endIndex < sql.length && depth > 0) {
            const ch = sql[endIndex];
            if (ch === "(")
                depth++;
            else if (ch === ")")
                depth--;
            endIndex++;
        }
        const body = sql.slice(startIndex, endIndex - 1);
        createTableHeadRegex.lastIndex = endIndex;
        const cleanTableName = rawTableName.replace(/[`"']/g, "").split(".").pop() || rawTableName;
        const columns = [];
        const foreignKeys = [];
        // Split body by top-level commas (handling nested parentheses)
        const elements = [];
        let parenDepth = 0;
        let currentElem = "";
        for (let i = 0; i < body.length; i++) {
            const char = body[i];
            if (char === "(")
                parenDepth++;
            else if (char === ")")
                parenDepth--;
            if (char === "," && parenDepth === 0) {
                elements.push(currentElem.trim());
                currentElem = "";
            }
            else {
                currentElem += char;
            }
        }
        if (currentElem.trim()) {
            elements.push(currentElem.trim());
        }
        for (const elem of elements) {
            const trimmed = elem.trim();
            if (!trimmed)
                continue;
            // Table-level Foreign Key: FOREIGN KEY (col) REFERENCES target(target_col)
            const fkMatch = /(?:CONSTRAINT\s+[`"']?([a-zA-Z0-9_]+)[`"']?\s+)?FOREIGN\s+KEY\s*\(\s*[`"']?([a-zA-Z0-9_]+)[`"']?\s*\)\s*REFERENCES\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s*(?:\(\s*[`"']?([a-zA-Z0-9_]+)[`"']?\s*\))?/i.exec(trimmed);
            if (fkMatch) {
                const constraintName = fkMatch[1];
                const fromCol = fkMatch[2];
                const rawTarget = fkMatch[3];
                const toCol = fkMatch[4] || "id";
                const cleanTarget = rawTarget.replace(/[`"']/g, "").split(".").pop() || rawTarget;
                foreignKeys.push({
                    fromColumn: fromCol,
                    targetTable: cleanTarget.toLowerCase(),
                    toColumn: toCol,
                    constraintName,
                });
                continue;
            }
            // Table-level Primary Key: PRIMARY KEY (col1, col2)
            if (/^PRIMARY\s+KEY/i.test(trimmed)) {
                const pkMatch = /PRIMARY\s+KEY\s*\(([^)]+)\)/i.exec(trimmed);
                if (pkMatch) {
                    const pkCols = pkMatch[1].split(",").map(c => c.replace(/[`"'\s]/g, ""));
                    for (const col of columns) {
                        if (pkCols.includes(col.name)) {
                            col.isPrimaryKey = true;
                        }
                    }
                }
                continue;
            }
            // Check for other table-level constraints (UNIQUE, CHECK)
            if (/^(?:CONSTRAINT|UNIQUE|CHECK)/i.test(trimmed)) {
                continue;
            }
            // Column definition
            const colTokens = trimmed.split(/\s+/);
            if (colTokens.length >= 2) {
                const colName = colTokens[0].replace(/[`"']/g, "");
                const dataType = colTokens[1].toUpperCase();
                const isPrimaryKey = /PRIMARY\s+KEY/i.test(trimmed);
                const isNotNull = /NOT\s+NULL/i.test(trimmed);
                columns.push({
                    name: colName,
                    dataType,
                    isPrimaryKey,
                    nullable: !isNotNull,
                });
                // Inline REFERENCES: col INT REFERENCES target_table(id)
                const inlineFkMatch = /REFERENCES\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s*(?:\(\s*[`"']?([a-zA-Z0-9_]+)[`"']?\s*\))?/i.exec(trimmed);
                if (inlineFkMatch) {
                    const rawTarget = inlineFkMatch[1];
                    const toCol = inlineFkMatch[2] || "id";
                    const cleanTarget = rawTarget.replace(/[`"']/g, "").split(".").pop() || rawTarget;
                    foreignKeys.push({
                        fromColumn: colName,
                        targetTable: cleanTarget.toLowerCase(),
                        toColumn: toCol,
                    });
                }
            }
        }
        const tableKey = cleanTableName.toLowerCase();
        catalog.tables[tableKey] = {
            name: cleanTableName,
            type: "table",
            columns,
            foreignKeys,
            sourceFile,
        };
    }
    // 2. Match CREATE VIEW statements
    const createViewRegex = /CREATE(?:\s+OR\s+REPLACE)?\s+VIEW\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s+AS\s+([\s\S]*?)(?:;|$)/gi;
    while ((match = createViewRegex.exec(sql)) !== null) {
        const rawViewName = match[1];
        const cleanViewName = rawViewName.replace(/[`"']/g, "").split(".").pop() || rawViewName;
        const viewKey = cleanViewName.toLowerCase();
        if (!catalog.tables[viewKey]) {
            catalog.tables[viewKey] = {
                name: cleanViewName,
                type: "view",
                columns: [],
                foreignKeys: [],
                sourceFile,
            };
        }
    }
    // 3. Match ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY statements
    const alterFkRegex = /ALTER\s+TABLE\s+(?:ONLY\s+)?([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s+ADD\s+(?:CONSTRAINT\s+[`"']?([a-zA-Z0-9_]+)[`"']?\s+)?FOREIGN\s+KEY\s*\(\s*[`"']?([a-zA-Z0-9_]+)[`"']?\s*\)\s*REFERENCES\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)\s*(?:\(\s*[`"']?([a-zA-Z0-9_]+)[`"']?\s*\))?/gi;
    while ((match = alterFkRegex.exec(sql)) !== null) {
        const rawSrcTable = match[1];
        const constraintName = match[2];
        const fromCol = match[3];
        const rawTargetTable = match[4];
        const toCol = match[5] || "id";
        const cleanSrc = rawSrcTable.replace(/[`"']/g, "").split(".").pop() || rawSrcTable;
        const cleanTarget = rawTargetTable.replace(/[`"']/g, "").split(".").pop() || rawTargetTable;
        const srcKey = cleanSrc.toLowerCase();
        const targetKey = cleanTarget.toLowerCase();
        if (!catalog.tables[srcKey]) {
            catalog.tables[srcKey] = {
                name: cleanSrc,
                type: "table",
                columns: [],
                foreignKeys: [],
                sourceFile,
            };
        }
        catalog.tables[srcKey].foreignKeys.push({
            fromColumn: fromCol,
            targetTable: targetKey,
            toColumn: toCol,
            constraintName,
        });
    }
    return catalog;
}
//# sourceMappingURL=sqlParser.js.map