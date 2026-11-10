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

Implemented:
- “Investigate your home” joins the existing Pi Web navigation links and opens a
  separate starter page with five workflows.
- Explain/debug use automation pickers; unexpected/missing behavior use entity
  pickers, a behavior description and an optional local incident time. Health
  checks require no inputs. Entity IDs can be entered when discovery is unavailable.
- Submitting creates a new conversation in the registered Home Assistant scratch
  project, checks that the selected skill is available, submits its command with
  structured context and opens that session in Pi Web. Failed submissions retain
  the session link and prepared request without automatically resubmitting.
- Debug reuses Phase 4's house-debug-automation skill and last-five-runs default.
- House health checks also discover HAGHS when available, interpret its exposed
  scores/recommendations and corroborate significant findings. Missing HAGHS does
  not prevent the standard check. All investigation instructions remain in skills.

Validation of live HA investigations still requires a configured target installation.
