---
name: "mac-storage-manager"
description: "Audit and manage macOS disk usage safely with staged cleanup and rollback-minded operations. Use when the request clearly belongs to this skill domain. Do not use for unrelated tasks."
---

# Mac Storage Manager

## Trigger
Use this skill when user asks to clean disk, free storage, find large files, remove caches, or reduce macOS space pressure.

## Principles
- Safety first: default to read-only audit.
- Never delete personal media/documents unless user explicitly points to paths.
- Prefer reversible cleanup (`trash`) for user files.
- Prioritize regenerable data: caches, logs, temp artifacts, old tool downloads.

## Workflow
1. Run `scripts/audit_storage.sh` to produce a markdown report from the Python core.
2. Always list the exact cleanup candidates first, including target IDs, blocked items, and anything explicitly out of scope.
3. Convert any user-facing numbered choices back into exact `target_id` values before execution.
4. Build an approved cleanup list and echo that exact list back before apply.
5. Before apply, show the cleanup plan plus blocked/high-risk targets so the user can see what will not be touched.
6. Run `scripts/safe_clean.sh` only after user confirms low-risk cleanup. `safe_clean.sh` must not unlock medium/high-risk targets by itself; Downloads, Trash, Docker, app leftovers, system paths, hidden home items, and other out-of-plan targets require exact target confirmation and must stay inside the approved list.
7. Re-run audit and show before/after delta.

## Safe targets
- `~/Library/Caches/*`
- `~/Library/Logs/*`
- `~/.npm/_cacache`, `~/.pnpm-store`, `~/Library/Caches/pip`
- Playwright browser caches when not used (`~/Library/Caches/ms-playwright`)
- Xcode DerivedData (`~/Library/Developer/Xcode/DerivedData`)

## Confirmation semantics

- Generic `--yes` applies low-risk cleanup only.
- Exact `target_id` confirmation can unlock that one target.
- Exact approved cleanup list is required before hidden-home or other sensitive cleanup; confirmation alone is not enough if the target is outside the approved list.
- Category-level confirmation is allowed only for low-risk targets.
- Medium/high-risk targets stay blocked unless named through `--confirm-targets <exact-target-id>`.
- Never treat a broad user phrase like "clean caches" as permission to clean Downloads, Trash, Docker, app leftovers, or personal documents.
- Never treat a numbered UI choice as permission by itself; resolve it to the exact target IDs and echo them before running apply.
- Cleanup execution must strictly follow the user-confirmed list and must not touch anything outside that list.

## High-risk targets (explicit confirmation required)
- `~/Downloads` bulk deletion
- VM/Docker images
- media libraries (`Photos`, `Movies`)
- app support data containing tokens/sessions

## Output format
Provide:
- Top space consumers
- Exact approved cleanup list
- What was cleaned or planned
- Estimated reclaimed GB
- Free before/after
- Residual hotspots and next options

## When to use
- Use this skill when the task clearly matches the skill description and domain.

## Output contract
- Provide: root conclusion, actions taken, verification status, free-space delta, and next safe step.
- Default to audit-first behavior; `safe_clean.sh` maps to `clean --apply --yes`, where `--yes` is intentionally limited to low-risk targets.
- Include blocked/high-risk targets in the pre-apply summary whenever they have reclaimable bytes.
- For hidden home folders, root-owned caches, app leftovers, or Trash batches, show the exact target list first and do not clean anything outside the approved target list.

## Safety And Scope Gates

- Use this skill only when the request clearly matches the skill domain.
- Do not execute out-of-scope actions, hidden fallback branches, or unrelated refactors.
- Require explicit user intent before risky operations (network, destructive file ops, privileged commands).
- Keep the shortest valid path to the objective; reject patch-only detours that hide root cause.
- If key motivation or acceptance criteria are unclear, pause and request clarification before execution.

## Verification And Release Criteria

- Run a scoped validation pass after major edits using available checks (`test`, `validate`, `check`, or equivalent smoke path).
- Confirm pass/fail criteria explicitly before marking completion.
- Include one negative-path check (error/invalid input) where applicable.
- Report verification evidence: commands executed, observed result, and residual risks.
- Treat shared reports as public by default: redact user-specific absolute paths and sensitive diagnostic details unless the operator explicitly asks for raw output.

## Security And Privacy Controls

- Avoid exposing secrets, tokens, credentials, or sensitive data in outputs/logs.
- Redact sensitive values in examples and diagnostic snippets.
- Treat external inputs as untrusted; validate before use.
- Minimize agency: do not perform privileged or irreversible actions without explicit permission.


## Business Objective

- Increase operational reliability and decision quality for recurring engineering workflows.
- Reduce rework by enforcing explicit constraints and repeatable execution patterns.

## Target Users And Scenarios

- Primary: maintainers/operators managing long-running repo and agent workflows.
- Secondary: collaborators requiring observable, auditable execution state.

## Business Deliverables

- Provide operationally actionable outputs (checks, plans, diffs, status evidence).
- Provide concise residual-risk statement for follow-up decisions.

## Business Acceptance Criteria

- Requested workflow is completed with evidence and no hidden side effects.
- Policy and guardrail requirements are satisfied for in-scope actions.
- Outputs are usable for immediate next-step execution.

## Business Boundaries And Non-Goals

- Do not bypass repository/user hard constraints for speed.
- Do not silently broaden scope beyond requested operational objective.

## Business Risks And Constraints

- Risk: automation overreach; mitigate with explicit gates and user-intent checks.
- Risk: stale operational assumptions; mitigate with fresh preflight verification.
