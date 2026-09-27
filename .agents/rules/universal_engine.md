# Rule: Universal Multi-Backend & Zero-Config Autonomy

1. **Universal Language Coverage**: SystemLens is NOT Python-exclusive. All core capabilities must support the primary enterprise backend ecosystems: Python, JavaScript/TypeScript, Go, Java/Kotlin, Ruby, PHP, and generic SQL-using languages (Rust, C#).
2. **Zero-Config Workspace Discovery**: When an arbitrary repository is opened in the IDE, SystemLens must automatically discover languages, frameworks, migration files, and database schemas with zero required user configuration or manual CLI pre-steps.
3. **Runtime Independence**: The IDE extension must operate self-contained (native in TypeScript or bundled self-executing engine) without assuming that Python, uv, or specific language package managers are installed on the host machine.
4. **Honesty & Tiered Degradation**: If live database credentials or explicit schemas are absent, SystemLens must degrade gracefully by extracting schemas from migrations (.sql, Prisma, ActiveRecord) or inferring models from code, disclosing any unanalyzed boundaries in the Blind Spots layer.
5. **No Single-Repo Bias**: Benchmarks, tests, and documentation must treat all backend ecosystems equally and not tailor features exclusively to a single target repository.
