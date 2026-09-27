"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SystemLensDecorationProvider = void 0;
const vscode = require("vscode");
class SystemLensDecorationProvider {
    staticSqlDecorationType;
    ormCallDecorationType;
    dynamicSqlDecorationType;
    constructor() {
        const blueDot = vscode.Uri.parse('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" fill="%233b82f6"/></svg>');
        const yellowDot = vscode.Uri.parse('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" fill="%23eab308"/></svg>');
        const redDot = vscode.Uri.parse('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" fill="%23ef4444"/></svg>');
        this.staticSqlDecorationType = vscode.window.createTextEditorDecorationType({
            gutterIconPath: blueDot,
            gutterIconSize: "contain",
            overviewRulerColor: "#3b82f6",
            overviewRulerLane: vscode.OverviewRulerLane.Right,
        });
        this.ormCallDecorationType = vscode.window.createTextEditorDecorationType({
            gutterIconPath: yellowDot,
            gutterIconSize: "contain",
            overviewRulerColor: "#eab308",
            overviewRulerLane: vscode.OverviewRulerLane.Right,
        });
        this.dynamicSqlDecorationType = vscode.window.createTextEditorDecorationType({
            gutterIconPath: redDot,
            gutterIconSize: "contain",
            overviewRulerColor: "#ef4444",
            overviewRulerLane: vscode.OverviewRulerLane.Right,
        });
    }
    static SUPPORTED_LANGS = new Set([
        "python",
        "javascript",
        "typescript",
        "javascriptreact",
        "typescriptreact",
        "go",
        "java",
        "ruby",
        "php",
        "rust",
        "csharp",
        "c",
        "cpp",
        "sql",
    ]);
    updateDecorations(editor) {
        if (!editor) {
            return;
        }
        const document = editor.document;
        const lang = document.languageId;
        if (!SystemLensDecorationProvider.SUPPORTED_LANGS.has(lang)) {
            return;
        }
        const text = document.getText();
        const lines = text.split("\n");
        const staticSqlDecorations = [];
        const ormCallDecorations = [];
        const dynamicSqlDecorations = [];
        // Static SQL regex (literal SELECT/INSERT/UPDATE/DELETE/FROM in string)
        const sqlRegex = /["'`](?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE)\b/i;
        // Multi-backend ORM call patterns:
        // - Python: objects.filter/create, session.query
        // - JS/TS: findMany, findUnique, create, update, destroy
        // - Go: db.Find, db.Where, db.Create, db.Table
        // - Java: @Query, findBy, findAll, save
        // - Ruby: .where, .find_by, .create
        // - PHP: DB::table, ->where, ->find
        const ormRegex = /\b(?:objects\.(?:filter|get|create|update|all|exclude|values)|query\.(?:filter|all|first)|session\.query|\.(?:findAll|findUnique|findMany|create|update|destroy|where|find_by|FindBy)\s*\(|db\.(?:Find|Where|Create|Table|First)\s*\(|DB::table\s*\(|@Query\s*\()/;
        // Dynamic execution without static literal (execute(var), raw(var), db.Raw(var), etc.)
        const dynamicRegex = /\b(?:cursor\.execute|execute|raw|client\.query|db\.Raw|db\.Exec|em\.createNativeQuery|DB::raw|DB::statement)\s*\(\s*[$a-zA-Z_][a-zA-Z0-9_]*\s*[,)]/;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const range = new vscode.Range(i, 0, i, line.length);
            if (dynamicRegex.test(line) && !sqlRegex.test(line)) {
                dynamicSqlDecorations.push({
                    range,
                    hoverMessage: new vscode.MarkdownString("🔴 **SystemLens: Unresolved Dynamic SQL**\n\nVariable or dynamic expression passed to database query. Cannot statically determine target table (Honesty Layer)."),
                });
            }
            else if (sqlRegex.test(line)) {
                staticSqlDecorations.push({
                    range,
                    hoverMessage: new vscode.MarkdownString("🔵 **SystemLens: Static SQL Literal**\n\nDirect SQL query string detected. Traced to database schema with 85% confidence."),
                });
            }
            else if (ormRegex.test(line)) {
                ormCallDecorations.push({
                    range,
                    hoverMessage: new vscode.MarkdownString("🟡 **SystemLens: ORM Model Call**\n\nORM query method invocation detected. Traced to underlying table with 80% confidence."),
                });
            }
        }
        editor.setDecorations(this.staticSqlDecorationType, staticSqlDecorations);
        editor.setDecorations(this.ormCallDecorationType, ormCallDecorations);
        editor.setDecorations(this.dynamicSqlDecorationType, dynamicSqlDecorations);
    }
    dispose() {
        this.staticSqlDecorationType.dispose();
        this.ormCallDecorationType.dispose();
        this.dynamicSqlDecorationType.dispose();
    }
}
exports.SystemLensDecorationProvider = SystemLensDecorationProvider;
//# sourceMappingURL=decorations.js.map