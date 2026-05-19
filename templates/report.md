# macOS Storage Report

## Summary
- Mode:
- Free before:
- Free after:
- Estimated reclaimed:
- Actual reclaimed:
- Approved targets:

## Top Consumers
1. `<TARGET_ID>` — source_layer= — protection= — reclaimable=
2.
3.

## Cleanup Boundary
- Exact approved cleanup list:
- Blocked targets:
- Out-of-scope targets:
- Protected session/key material:

## Cleaned / Planned
- `<TARGET_ID>` [status] [scope] layer= protection= rollback= reason=

## Backup / Receipt
- Backup dir:
- Touched manifest:
- SHA256 manifest:
- Receipt markdown:
- Receipt JSON:

## Residual Validation
- `<KEYWORD>` [pass/fail] hits= command=`rg -n -S <KEYWORD>`

## Remaining Hotspots
- 

## Next Step Options
1. Re-run `audit` or `plan` to review the exact target list.
2. Re-run with `--approved-targets <TARGET_ID>` and required `--confirm-targets <TARGET_ID>` after reviewing blocked targets.
3. For reappearing folders, run `trace --path <TARGET_PATH> --keyword <KEYWORD>` before deletion.
