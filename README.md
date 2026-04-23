![Mac Storage Manager header](assets/readme-header.svg)

# Mac Storage Manager
给 macOS 的安全清理技能包。<br>
A safety-first cleanup skill package for macOS.

## 这是什么
这是一个先审计、再计划、最后才执行的 macOS 磁盘管理技能包。<br>
It audits first, plans second, and only executes last.

它优先处理低风险、可恢复的空间垃圾，把高风险内容留在确认门槛后面。<br>
It prefers low-risk, recoverable cleanup and keeps high-risk items behind explicit confirmation.

## 核心功能
- 默认只做审计，不会上来就动盘。<br>
  By default it only audits, so nothing gets touched too early.
- 高风险目标必须确认，系统不会替你逞强。<br>
  High-risk targets require confirmation, and the system will not try to be brave on your behalf.
- 缺少 `brew`、`docker`、`flutter` 或 `xcrun` 时会跳过，不会硬装懂。<br>
  Missing `brew`, `docker`, `flutter`, or `xcrun` is skipped rather than faked.
- 会给出清理前后空间、估算回收量和剩余热点。<br>
  It reports before/after free space, estimated reclaimed size, and remaining hotspots.
- 兼容任何能读 `SKILL.md`、跑 shell 和 Python 的智能体。<br>
  Any agent that can read `SKILL.md` and run shell/Python can use it.

## 怎么用
先跑只读审计，看看盘面再说。<br>
Start with a read-only audit and inspect the terrain first.

```bash
bash scripts/audit_storage.sh
```

需要执行时，先用 dry run 过一遍计划。<br>
When you are ready, run a dry run first.

```bash
bash scripts/safe_clean.sh --dry-run
```

确认计划没问题，再正式执行。<br>
Once the plan looks sane, run the real cleanup.

```bash
bash scripts/safe_clean.sh
```

## 安全边界
- 不会默认删 `Downloads`、媒体库、文档，或带会话和令牌的应用数据。<br>
  It will not default-delete `Downloads`, media libraries, documents, or app data with sessions and tokens.
- 目标缺失会跳过，不会瞎编路径。<br>
  Missing targets are skipped instead of inventing paths.
- 审计永远在前，执行永远在后。<br>
  Audit always comes first, execution always comes last.

## 兼容性
- 只要智能体能读 `SKILL.md`、跑 shell 和 Python，就能用。<br>
  Any agent that can read `SKILL.md` and run shell/Python can use it.
- `agents/openai.yaml` 只是加载器元数据，不是硬依赖。<br>
  `agents/openai.yaml` is loader metadata, not a hard dependency.
- 核心脚本不绑机器、不绑用户名，也不偷偷记住你的电脑名。<br>
  The core scripts do not bind to a machine, username, or local nickname.

## 文件
- `SKILL.md` 是技能契约。<br>
  `SKILL.md` is the skill contract.
- `scripts/audit_storage.sh` 负责只读审计。<br>
  `scripts/audit_storage.sh` runs read-only audit mode.
- `scripts/safe_clean.sh` 负责确认后的执行。<br>
  `scripts/safe_clean.sh` handles confirmed cleanup.
- `templates/report.md` 提供报告模板。<br>
  `templates/report.md` provides the report template.
- `LICENSE` 使用 MIT。<br>
  `LICENSE` uses MIT.

## 维护者
由 **AI·Maho** 和 **人类·Matoya** 共同维护，认真时能干活，松弛时也不装。<br>
Maintained jointly by **AI·Maho** and **Human·Matoya**; serious when needed, relaxed without pretending.
