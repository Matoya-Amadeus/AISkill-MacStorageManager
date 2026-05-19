---
name: "mac-storage-manager"
description: "Audit and manage macOS disk usage safely with staged cleanup, source tracing, redacted reports, and rollback-minded operations. Use when the request clearly belongs to this skill domain. Do not use for unrelated tasks."
---

# Mac Storage Manager

## Trigger
Use this skill when a user asks to clean disk, free storage, find large files, remove caches, reduce macOS space pressure, or diagnose a folder/app/cache that keeps reappearing after deletion.

## Principles
- Safety first: default to read-only audit.
- Reappearance first: if a folder regenerates, identify the trigger chain before deleting runtime artifacts.
- Never delete personal media/documents unless the user explicitly points to exact paths.
- Prefer reversible cleanup (`trash`) for user files.
- Prioritize regenerable data: caches, logs, temp artifacts, old tool downloads.
- Protect browser identity/session data and credentials by default.
- Treat shared reports as public by default: redact home, root, private absolute paths, and sensitive diagnostic details.

## Source Layers
Classify every finding/target before proposing cleanup:

- `active_trigger`: LaunchAgents, LaunchDaemons, Docker containers, shell startup, scheduled launchers.
- `runtime_artifact`: caches, logs, build outputs, temp files.
- `repo_reference`: scripts, configs, skill docs, IDE/project references.
- `historical_index`: metrics, audit receipts, graph JSONL, SBOM/provenance, generated snapshots, eval suites.
- `user_data`: Downloads, Trash, media, documents, hidden home folders.
- `protected_session`: browser identity/session/cookie/login/token/key material.

## Workflow
1. Clarify the target path and/or keyword.
2. For reappearing folders, run `scripts/mac_storage_manager.py trace --path <TARGET_PATH> --keyword <KEYWORD>` and remove `active_trigger` causes first.
3. Run `scripts/audit_storage.sh` to produce a read-only markdown report.
4. List exact cleanup candidates, `target_id`, `source_layer`, protection level, blocked items, and explicit out-of-scope items.
5. Convert any user-facing numbered choices back into exact `target_id` values before execution.
6. Build the approved cleanup list and echo that exact list before apply.
7. Run `scripts/safe_clean.sh` or `clean --apply` only after confirmation; then re-audit and run scoped residual search with `--require-zero-hit <PATTERN>` when a keyword/path was part of the task.

## Safe Targets
- `~/Library/Caches/*`
- `~/Library/Logs/*`
- `~/.npm/_cacache`, `~/.pnpm-store`, `~/Library/Caches/pip`
- Playwright browser caches when not used (`~/Library/Caches/ms-playwright`)
- Xcode DerivedData (`~/Library/Developer/Xcode/DerivedData`)

## Confirmation Semantics
- Generic `--yes` applies low-risk cleanup only.
- Medium/high-risk cleanup requires the exact `target_id` in `--approved-targets`; if the target also requires confirmation, it also needs exact `--confirm-targets <TARGET_ID>`.
- Exact approved cleanup list is required before hidden-home, Docker, Trash, Downloads, app leftovers, system paths, and other sensitive cleanup.
- Category-level confirmation is allowed only for low-risk targets.
- Never treat a broad phrase like "clean caches" as permission to clean Downloads, Trash, Docker, app leftovers, hidden-home items, or personal documents.
- Cleanup execution must strictly follow the user-confirmed list and must not touch anything outside that list.

## High-Risk / Blocked Targets
- Downloads bulk deletion.
- Trash cleanup.
- VM/Docker images and `docker system prune`.
- hidden-home folders and repo metadata such as `~/.git`.
- App support data containing token/session state.
- Firefox/Chrome/Safari/OpenAI/ChatGPT cookies, local storage, login DBs, sessionstore, Keychain, `.ssh`, and credential material are `protected_session` and blocked by default.

## Output Format
Provide:
- Top space consumers.
- Exact approved cleanup list.
- Source layer (`active_trigger`, `runtime_artifact`, `repo_reference`, `historical_index`, `user_data`, `protected_session`).
- Protection level (`normal`, `exact_confirm`, `approved_plan`, `blocked`).
- Rollback strategy (`none`, `trash`, `backup_manifest`, `copy_backup`).
- What was cleaned or planned.
- Backup manifest and cleanup receipt path for apply runs.
- Residual validation status for any `--require-zero-hit` pattern.
- Estimated reclaimed GB and free before/after.
- Residual hotspots and next safe options.

## Verification And Release Criteria
- Run a scoped validation pass after major edits using available checks (`python3 -m unittest`, `py_compile`, or equivalent smoke path).
- Include one negative-path check where applicable.
- Confirm trace reports, cleanup reports, receipts, and sample hits do not expose private absolute paths, usernames, tokens, cookies, session values, or machine-specific paths.
- Confirm pass/fail criteria explicitly before marking completion.

## Security And Privacy Controls
- Avoid exposing secrets, tokens, credentials, or sensitive data in outputs/logs.
- Redact sensitive values in examples and diagnostic snippets.
- Treat external inputs as untrusted; validate before use.
- Minimize agency: do not perform privileged or irreversible actions without explicit permission.
- Default-block browser/session/key material; do not offer a normal confirmation bypass for protected session data.
