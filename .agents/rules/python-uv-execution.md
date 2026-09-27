# Rule: Python and Tool Execution via UV on Windows

## Context
In this Windows environment, Python is managed using `uv`. Direct invocation of scripts or binaries inside `.venv\Scripts\` (e.g. `.venv\Scripts\pytest.exe` or `.venv\Scripts\python.exe`) can fail with Windows path canonicalization errors (`uv trampoline failed to canonicalize script path`).

## Rules
1. **Always invoke tools with `uv run`**:
   - Run tests: `uv run pytest -v`
   - Run scripts: `uv run python scripts/<script_name>.py`
   - Run modules / CLI: `uv run python -m systemlens.cli ...`
2. **Terminal command execution**:
   - Use `BypassSandbox: true` when running Python/uv terminal commands since the active Python runtime may reside outside the default sandbox boundary.
