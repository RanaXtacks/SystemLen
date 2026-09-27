/**
 * Schema types for SystemLens native schema discovery.
 */

export interface ColumnDefinition {
  name: string;
  dataType?: string;
  nullable?: boolean;
  isPrimaryKey?: boolean;
  default?: string | null;
}

export interface ForeignKeyDefinition {
  fromColumn: string;
  targetTable: string;
  toColumn?: string;
  constraintName?: string;
}

export interface TableDefinition {
  name: string;
  schema?: string;
  type: "table" | "view";
  columns: ColumnDefinition[];
  foreignKeys: ForeignKeyDefinition[];
  sourceFile?: string;
}

export interface SchemaCatalog {
  sourceType: string;
  tables: Record<string, TableDefinition>;
}
