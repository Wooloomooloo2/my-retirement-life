"""Import-from-My-Financial-Life support (ADR-020).

Phase 1: a read-only reader that turns a user-selected MFL ``.mfl`` SQLite file
into an in-memory snapshot (`reader.read_snapshot`). No store writes, no engine
changes — the mapping to MRL entities lives in a later phase.
"""
