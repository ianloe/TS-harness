# Architecture and Design Decisions

All dates are recorded in ISO 8601 format. British English is used throughout.

## 2026-11-22: Foundation Decisions (Phase 1)

1. **SQLite WAL Mode and Foreign Keys**: When using SQLite, `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` are enabled on every connection so concurrent reads and referential integrity are enforced.
2. **Currency Restriction**: Only `SGD` and `USD` are permitted by `Currency` validation in configuration, budget ledgers, and audit logs. Any other currency raises a validation error.
3. **Append-Only Hash-Chained Audit Log**: Each `AuditLogRecord` computes a SHA-256 hash over its canonical fields and the previous entry's hash (`GENESIS` for the first entry). Secret-like values are redacted before persistence and before structured logging.
4. **Deny-by-Default Tool Gateway**: Tools cannot execute unless an explicit policy checker grants permission. In Phase 1, the default `PolicyChecker` denies all calls unless explicitly allowed; Phase 2 replaces this with the full YAML policy engine.
5. **No Global Mutable State**: Database engines, session factories, audit loggers, budget managers, and kill-switch managers are constructed explicitly and passed via dependency injection.
