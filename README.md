# Mac Storage Manager 技能包
给 macOS 磁盘清理准备的安全感十足的技能包。
A safety-first skill package for cleaning macOS disk usage.

## 这是什么 / What it is
这不是那种“看起来很会删，实际很会翻车”的清理器。
它先审计、再计划、最后才执行，尽量把能恢复的东西留在原地。
This is not the kind of cleaner that looks clever and then deletes your weekend by accident.
It audits first, plans second, and only executes last, keeping recoverable data where it belongs.

## 亮点 / Highlights
- 默认先审计，再清理。  
  Audit first, clean later.
- 高风险目标必须明确确认，系统不会替你逞强。  
  High-risk targets require explicit confirmation, and the system will not be brave on your behalf.
- 缺少 `brew`、`docker`、`flutter` 或 `xcrun` 时会自动跳过，不装懂。  
  Missing `brew`, `docker`, `flutter`, or `xcrun` is skipped automatically; no pretending.
- 报告会给出前后空间、估算回收量和剩余热点。  
  Reports show before/after space, estimated reclaimed bytes, and remaining hotspots.
- 它靠路径和门禁做事，不靠玄学和手感。  
  It works with paths and gates, not vibes and guesswork.

## 快速开始 / Quick Start
1. 先做只读审计，别上来就动刀。  
   Start with a read-only audit, not with the delete button.
   ```bash
   bash scripts/audit_storage.sh
   ```
2. 看报告，确认哪些是低风险，哪些得先问一声。  
   Review the report and separate low-risk cleanup from anything that needs a human nod.
3. 需要执行时再清理，并先确认结果可接受。  
   Run cleanup only after confirmation and after the plan looks sane.
   ```bash
   bash scripts/safe_clean.sh --dry-run
   bash scripts/safe_clean.sh
   ```

## 安全边界 / Safety
- 不会默认删 `Downloads`、媒体库或带会话和令牌的应用数据。  
  It will not default-delete `Downloads`, media libraries, or app data with sessions and tokens.
- 真要动高风险目标，必须先确认。  
  High-risk targets require explicit confirmation.
- 审计永远先于执行。  
  Audit always comes before execution.
- 目标缺失时会跳过，不会硬编一个“应该存在”。  
  Missing targets are skipped instead of being imagined into existence.

## 兼容性 / Compatibility
- 只要智能体能读 `SKILL.md`、跑 shell 和 Python，就能用。  
  Any host that can read `SKILL.md` and run shell/Python can use it.
- `agents/openai.yaml` 只是加载器元数据，不是硬依赖。  
  `agents/openai.yaml` is loader metadata, not a hard dependency.
- 核心脚本不绑机器、不绑用户名，也不偷偷记住你的电脑名。  
  The core scripts do not bind to a machine, username, or local nickname.

## 文件 / Files
- `SKILL.md` 是技能契约。  
  `SKILL.md` is the skill contract.
- `scripts/audit_storage.sh` 负责只读审计。  
  `scripts/audit_storage.sh` runs read-only audit mode.
- `scripts/safe_clean.sh` 负责确认后的执行。  
  `scripts/safe_clean.sh` handles confirmed cleanup.
- `agents/openai.yaml` 只是可选展示元数据。  
  `agents/openai.yaml` is optional presentation metadata.
- `LICENSE` 使用 MIT。  
  `LICENSE` uses MIT.

## 输出 / Output
- 会告诉你最占空间的东西、清了多少、还剩什么热点。  
  It tells you the biggest consumers, what was reclaimed, and what hotspots remain.
- 还能给你前后空间对比，方便判断这次有没有真的瘦下来。  
  It also gives before/after free-space so you can tell whether the machine actually slimmed down.

## 维护者 / Maintainers
由 **AI·Maho** 和 **人类·Matoya** 共同维护，认真时能干活，松弛时也不装。
Maintained jointly by **AI·Maho** and **Human·Matoya**; serious when needed, relaxed without pretending.
