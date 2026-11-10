# Feature follow-up

Phase 4 now covers shared repository conventions and automation debugging.
Phase 5 (background task status and completion notifications) remains out of scope.

## Phase 4: Repository conventions and automation debugging

Implemented:
- Shared agent guidance applies configured push/PR conventions to all repository
  changes, including normal conversation; existing installations receive updates.
- `butler-workspace settings` exposes current delivery/branch settings without
  credentials. `prepare NAME` uses the configured destination branch directly in
  push mode, or creates a task worktree from the configured base in PR mode.
- Dirty/divergent work is preserved. Concurrent sessions must defer or explicitly
  arrange isolation instead of automatically creating task branches in push mode.
- `debug-automation` resolves a name/ID, reviews the last five retained executions
  by default, and explains outcomes using traces, relevant history and Core logs.
  It reports unavailable evidence and remains read-only.

No dedicated automation creation skill is planned: ordinary conversation already
supports research, templates, automation changes and configured Git delivery.
Revisit only if additional useful context is identified beyond shared conventions
and house memory. Fix verification and scheduled follow-up are skipped entirely.
Git delivery may deploy through the user's separate HA Git app; syntax checks
alone do not prove HA behavior.

## Phase 6: One-click workflow starters

Potential UI entry points with entity/automation pickers:
- Explain this automation.
- Debug this automation's recent executions.
- Investigate unexpected behavior.
- Investigate missing behavior.
- Run a house health check.

These would launch the marketplace workflows with structured context. Discuss
placement, what the user supplies, how a session opens and which starters are
useful before choosing an implementation. Keep workflow instructions in skills.
