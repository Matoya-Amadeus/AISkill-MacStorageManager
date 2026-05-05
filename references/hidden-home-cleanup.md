# Hidden Home Cleanup Rules

Use this reference when cleanup expands from normal caches into hidden home folders, container UUID directories, or ownership anomalies.

## Required sequence

1. Audit first.
2. List the exact candidate targets with `target_id`, size, and risk.
3. Mark blocked items and out-of-scope items explicitly.
4. Ask for confirmation on the exact list.
5. Apply cleanup only to the approved list.
6. Re-audit and report before/after delta.

## Special cases

### Home `.git`

- Treat `~/.git` as high-risk.
- Confirm it is really attached to the home directory before any cleanup.
- Never delete it from a broad "clean hidden files" request without exact approval.

### Hidden home folders

- Hidden home folders are not low-risk by default.
- Require both:
  - exact approved target list
  - exact `target_id` confirmation for risky items

### Root-owned cache files

- If a user-owned cache contains root-owned files, block normal cleanup.
- Report ownership mismatch and recommend a privileged remediation step before deletion.
- Do not silently escalate privileges.

### macOS app container UUID directories

- Resolve `Library/Containers/<UUID>` through `.com.apple.containermanagerd.metadata.plist`.
- Report the resolved bundle id before proposing cleanup.

### Sparse disk images

- Distinguish logical size from allocated size.
- Do not treat a sparse file's logical size as real reclaimable disk usage.
