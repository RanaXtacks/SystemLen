"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.parseActiveRecordSchema = parseActiveRecordSchema;
/**
 * Parses Ruby on Rails db/schema.rb files.
 */
function parseActiveRecordSchema(rubyText, sourceFile) {
    const catalog = {
        sourceType: "active_record",
        tables: {},
    };
    // Match create_table "users" ... do |t| ... end
    const tableRegex = /create_table\s+["']([a-zA-Z0-9_]+)["'][\s\S]*?do\s*\|[a-zA-Z0-9_]+\|([\s\S]*?)end/g;
    let match;
    while ((match = tableRegex.exec(rubyText)) !== null) {
        const tableName = match[1];
        const body = match[2];
        const tableKey = tableName.toLowerCase();
        const columns = [
            { name: "id", dataType: "INTEGER", isPrimaryKey: true, nullable: false }
        ];
        const foreignKeys = [];
        const lines = body.split("\n");
        for (const line of lines) {
            const trimmed = line.trim();
            const colMatch = /t\.([a-zA-Z0-9_]+)\s+["']([a-zA-Z0-9_]+)["']/i.exec(trimmed);
            if (colMatch) {
                const dataType = colMatch[1].toUpperCase();
                const colName = colMatch[2];
                columns.push({
                    name: colName,
                    dataType,
                    isPrimaryKey: false,
                    nullable: !trimmed.includes("null: false"),
                });
                // Check if column is a foreign key convention (e.g. user_id -> users)
                if (colName.endsWith("_id")) {
                    const targetTable = colName.slice(0, -3) + "s";
                    foreignKeys.push({
                        fromColumn: colName,
                        targetTable: targetTable.toLowerCase(),
                        toColumn: "id",
                    });
                }
            }
        }
        catalog.tables[tableKey] = {
            name: tableName,
            type: "table",
            columns,
            foreignKeys,
            sourceFile,
        };
    }
    // Match add_foreign_key "orders", "users"
    const fkRegex = /add_foreign_key\s+["']([a-zA-Z0-9_]+)["'],\s*["']([a-zA-Z0-9_]+)["']/g;
    while ((match = fkRegex.exec(rubyText)) !== null) {
        const fromTable = match[1].toLowerCase();
        const targetTable = match[2].toLowerCase();
        if (!catalog.tables[fromTable]) {
            catalog.tables[fromTable] = {
                name: fromTable,
                type: "table",
                columns: [],
                foreignKeys: [],
                sourceFile,
            };
        }
        // Avoid duplicate foreign key
        const exists = catalog.tables[fromTable].foreignKeys.some(fk => fk.targetTable === targetTable);
        if (!exists) {
            catalog.tables[fromTable].foreignKeys.push({
                fromColumn: `${targetTable.slice(0, -1)}_id`,
                targetTable,
                toColumn: "id",
            });
        }
    }
    return catalog;
}
//# sourceMappingURL=activeRecordParser.js.map