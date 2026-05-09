# ADR-004: Cross-platform portability approach

**Date:** 2026-05-09
**Status:** Accepted

---

## Context

My Retirement Life is developed on Windows (Visual Studio Code) but is intended to be deployable on Linux. The technology decisions in ADR-001, ADR-002, and ADR-003 were made with portability as a primary constraint. This ADR records the specific engineering practices that enforce portability throughout the codebase — independent of any single technology choice.

Without deliberate discipline, cross-platform issues accumulate silently and only surface when a Linux deployment is attempted. The goal is to make Linux compatibility a continuous property of the codebase, not a migration task.

---

## Decision

The following practices are adopted as project standards from the outset.

### 1. File paths

All file path construction must use Python's `pathlib.Path` rather than string concatenation or `os.path.join`. Hardcoded path separators (`\` or `/`) are not permitted outside of configuration files.

```python
# Correct
from pathlib import Path
data_dir = Path.home() / ".myretirementlife" / "data"

# Not permitted
data_dir = os.path.expanduser("~") + "\\myretirementlife\\data"
```

Platform-specific default paths (e.g. user data directory) are resolved at runtime using `platformdirs`, a cross-platform library for locating standard OS directories.

### 2. Line endings

A `.gitattributes` file is committed to the repository root enforcing LF line endings for all text-based source files. This prevents Windows CRLF characters from being committed and causing failures on Linux.

```
* text=auto
*.py text eol=lf
*.html text eol=lf
*.css text eol=lf
*.js text eol=lf
*.md text eol=lf
*.toml text eol=lf
*.yaml text eol=lf
*.json text eol=lf
```

### 3. Configuration and secrets

No credentials, connection strings, or environment-specific values are hardcoded. All configurable values are read from environment variables, with sensible defaults for local development. A `.env` file (excluded from version control via `.gitignore`) is used for local overrides.

The application uses **python-dotenv** to load `.env` on startup.

### 4. Data directory

User data (the Oxigraph triple store, settings, exports) is stored in the platform-appropriate user data directory resolved at runtime:

| Platform | Resolved path |
|----------|--------------|
| Windows | `%APPDATA%\MyRetirementLife\` |
| Linux | `~/.local/share/myretirementlife/` |
| macOS (future) | `~/Library/Application Support/MyRetirementLife/` |

This is resolved automatically by `platformdirs.user_data_dir("MyRetirementLife")`.

### 5. No platform-specific dependencies

Any Python dependency that requires compilation (native extensions) must be verified to have pre-built wheels for both Windows and Linux on PyPI. Dependencies that are Windows-only or Linux-only are not permitted in the core application. Platform-specific packaging dependencies (e.g. AppImage tooling) are confined to build scripts and not imported by the application itself.

### 6. Development environment

Development is conducted in Visual Studio Code with the Python extension. A `devcontainer.json` configuration will be provided so that contributors can optionally develop inside a Linux container on Windows, ensuring Linux compatibility is testable locally without a separate machine.

---

## Consequences

**Positive**
- Cross-platform issues are caught at development time rather than at migration time
- The codebase is Linux-ready from day one; migration is a packaging and deployment task, not a code rewrite
- `platformdirs` handles macOS as a future target with no additional work
- `.gitattributes` prevents the most common class of Windows/Linux interoperability bugs

**Trade-offs accepted**
- `pathlib` is slightly more verbose than string path manipulation; this is considered worthwhile
- Developers must verify cross-platform wheel availability before adding new dependencies — a small overhead on dependency selection
- The `devcontainer` setup requires Docker Desktop for developers who wish to use it; it is optional, not mandatory

**Ongoing responsibility**
- All pull requests (or Claude-generated code additions) should be reviewed against these standards before committing
- The dependency list should be audited for platform-specific packages whenever a new library is introduced
