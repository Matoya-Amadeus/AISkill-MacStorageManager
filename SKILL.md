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
2. Explain largest categories and proposed cleanup targets.
3. Run `scripts/safe_clean.sh` only after user confirms.
4. Re-run audit and show before/after delta.

## Compatibility
- Agent-neutral: any agent that can read `SKILL.md` and execute local shell/Python commands can use this skill.
- The workflow is not tied to any one agent runtime; `agents/openai.yaml` is optional UI metadata for loaders that support it.
- Optional tools (`brew`, `docker`, `flutter`, `xcrun`) are skipped when absent, so the skill still works in lean environments.

## Requirements
- macOS
- Python 3.10+
- `zsh` or another POSIX-compatible shell for the wrappers

## Safe targets
- `~/Library/Caches/*`
- `~/Library/Logs/*`
- `~/.npm/_cacache`, `~/.pnpm-store`, `~/Library/Caches/pip`
- Playwright browser caches when not used (`~/Library/Caches/ms-playwright`)
- Xcode DerivedData (`~/Library/Developer/Xcode/DerivedData`)

## High-risk targets (explicit confirmation required)
- `~/Downloads` bulk deletion
- VM/Docker images
- media libraries (`Photos`, `Movies`)
- app support data containing tokens/sessions

## Output format
Provide:
- Top space consumers
- What was cleaned or planned
- Estimated reclaimed GB
- Free before/after
- Residual hotspots and next options

## When to use
- Use this skill when the task clearly matches the skill description and domain.

## Output contract
- Provide: root conclusion, actions taken, verification status, free-space delta, and next safe step.
- Default to audit-first behavior; `safe_clean.sh` maps to `clean --apply --yes`.

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
