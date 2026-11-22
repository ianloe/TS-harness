# Default Policy Set

TS-Harness enforces **deny by default**: no tool call executes unless a rule in the active YAML policy file explicitly allows it and all hard safety invariants pass.

## Policy Files

- `policies/strict.yaml` (default): Permits `T0` read-only tools for trusted contexts (`user`, `system`, `trusted-tool`), permits `T1` reversible drafts/notes/holds only for explicit draft/note tool prefixes, holds all `T2` actions for human approval, and denies everything else.
- `policies/relaxed.yaml`: Permits `T0` read-only tools broadly and `T1` reversible writes for trusted contexts, while still requiring human approval for `T2` and blocking `T3`.

## Hard Safety Invariants (Non-Overridable)

1. **T3 Forbidden Actions**: Payments, credential entry, security setting changes, and trading are permanently denied regardless of YAML configuration.
2. **Untrusted Provenance Block**: Any `T1+` action whose justification traces solely to `untrusted-external` content is blocked unless explicitly approved by a human.

## Rule Dimensions

Each rule in `rules[]` can match on:
- `tools`: Tool name or glob pattern (for example `draft_*`).
- `action_tiers`: List of `T0`, `T1`, `T2`, `T3`.
- `resource_scopes`: Glob patterns matched against `resource`, `path`, `folder`, or `mailbox`.
- `recipients_or_domains`: Glob patterns matched against `recipient`, `to`, `domain`, or `url` host.
- `data_classes`: `public`, `internal`, `confidential`, `personal`.
- `time_window`: UTC hour range (`start_hour_utc`, `end_hour_utc`) and `days_of_week` (`0` = Monday).
- `max_amount`: Maximum numeric `amount` argument permitted.
- `trust_levels`: `user`, `system`, `trusted-tool`, `untrusted-external`.
