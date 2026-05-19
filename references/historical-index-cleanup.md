# Historical Index Cleanup

Use this reference when old project names remain in generated reports or repository evidence after runtime files are gone.

## Historical index families

- `manifests/metrics/**`
- `manifests/audit/**`
- `graph/**/*.jsonl`
- `manifests/supply-chain/sbom-*.spdx.json`
- `manifests/supply-chain/provenance-*`
- route maps, alias maps, eval suites, generated snapshots, and report rows

## Required behavior

1. Scope by explicit keyword/path; never perform a repo-wide fuzzy deletion without a target.
2. Dry-run or trace first and list exact files.
3. Back up touched files and write sha256 manifests before apply.
4. Regenerate dependent maps or eval suites when removal changes structured topics.
5. Validate with scoped residual search and relevant tests or schema checks.
6. Keep public reports redacted: use `<root>`, `~`, `<external>`, `<TARGET_ID>`, and `<KEYWORD>` placeholders in examples.
