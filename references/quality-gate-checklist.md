# Quality Gate Checklist

- Confirm trigger match and out-of-scope exclusions.
- For reappearing targets, confirm trace findings cover active triggers before runtime deletion.
- Confirm safety constraints and explicit intent gates.
- Confirm medium/high-risk targets have exact `--approved-targets` and any required exact `--confirm-targets`.
- Confirm protected browser/session/key material is blocked, not merely high-risk.
- Confirm apply runs produce receipt plus touched-files and sha256 manifests when required.
- Run scoped zero-hit validation for any keyword/path-based cleanup.
- Run unit tests and at least one CLI help/smoke check.
- Review privacy/security handling: no raw local paths, usernames, tokens, cookies, sessions, keys, or machine-specific paths in shared output.
