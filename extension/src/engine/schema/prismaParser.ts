import { SchemaCatalog, TableDefinition, ForeignKeyDefinition, ColumnDefinition } from "./types";

function pluralize(word: string): string {
  const lower = word.toLowerCase();
  if (lower.endsWith("y") && !/[aeiou]y$/.test(lower)) {
    return lower.slice(0, -1) + "ies";
  }
  if (lower.endsWith("s") || lower.endsWith("sh") || lower.endsWith("ch") || lower.endsWith("x") || lower.endsWith("z")) {
    return lower + "es";
  }
  return lower + "s";
}

/**
 * Parses Prisma schema text (.prisma files) and extracts models, fields, and relations.
 */
export function parsePrismaSchema(prismaText: string, sourceFile?: string): SchemaCatalog {
  const catalog: SchemaCatalog = {
    sourceType: "prisma",
    tables: {},
  };

  const modelRegex = /model\s+([a-zA-Z0-9_]+)\s*\{([\s\S]*?)\}/g;
  let modelMatch: RegExpExecArray | null;

  while ((modelMatch = modelRegex.exec(prismaText)) !== null) {
    const modelName = modelMatch[1];
    const body = modelMatch[2];

    // Check for explicit @@map("table_name")
    const mapMatch = /@@map\s*\(\s*["']([^"']+)["']\s*\)/i.exec(body);
    const tableName = mapMatch ? mapMatch[1] : pluralize(modelName);
    const tableKey = tableName.toLowerCase();

    const columns: ColumnDefinition[] = [];
    const foreignKeys: ForeignKeyDefinition[] = [];

    const lines = body.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("//") || trimmed.startsWith("@@")) continue;

      const tokens = trimmed.split(/\s+/);
      if (tokens.length >= 2) {
        const fieldName = tokens[0];
        const fieldType = tokens[1];
        const isId = trimmed.includes("@id");

        columns.push({
          name: fieldName,
          dataType: fieldType,
          isPrimaryKey: isId,
          nullable: fieldType.endsWith("?"),
        });

        // Check @relation(fields: [authorId], references: [id])
        const relationMatch = /@relation\s*\(([^)]*)\)/i.exec(trimmed);
        if (relationMatch) {
          const relationArgs = relationMatch[1];
          const fieldsMatch = /fields\s*:\s*\[([^\]]+)\]/i.exec(relationArgs);
          const referencesMatch = /references\s*:\s*\[([^\]]+)\]/i.exec(relationArgs);

          if (fieldsMatch) {
            const fromCol = fieldsMatch[1].trim();
            const toCol = referencesMatch ? referencesMatch[1].trim() : "id";
            // Field type points to target model name
            const targetModel = fieldType.replace(/[?\[\]]/g, "");
            const targetTable = pluralize(targetModel).toLowerCase();

            foreignKeys.push({
              fromColumn: fromCol,
              targetTable,
              toColumn: toCol,
            });
          }
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

  return catalog;
}
