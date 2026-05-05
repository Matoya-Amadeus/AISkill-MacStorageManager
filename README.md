<p align="center">
  <img src="assets/readme-header.svg" alt="Mac Storage Manager hero banner" width="100%">
</p>

<h1 align="center">Mac Storage Manager</h1>

<p align="center">
  安全分析和清理 macOS 磁盘空间：先审计、列清单、确认边界，再执行清理。<br>
  Analyze and clean macOS storage safely: audit first, list exact targets, approve the boundary, then clean.
</p>

<p align="center">
  <a href="#解决什么问题">解决什么问题</a> ·
  <a href="#安装">安装</a> ·
  <a href="#三分钟上手">三分钟上手</a> ·
  <a href="#配置与参数">配置与参数</a> ·
  <a href="#常见问题">FAQ</a>
</p>

<p align="center">
  <code>macOS only</code> · <code>Python stdlib</code> · <code>Audit first</code> · <code>Exact target IDs</code> · <code>Redacted reports</code>
</p>

## 解决什么问题
## What It Solves

Mac Storage Manager 不是“闭眼一键清理器”。它帮你先看清楚 Mac 上谁在占空间，再只对你确认过的范围执行清理。  
Mac Storage Manager is not a blind one-click cleaner. It helps you understand what is using space first, then cleans only the scope you approved.

<table>
<tr>
<td width="25%" valign="top">
<strong>找出空间热点</strong><br>
扫描缓存、日志、开发工具残留和可选敏感目录。<br>
<em>Find caches, logs, dev leftovers, and optional sensitive scopes.</em>
</td>
<td width="25%" valign="top">
<strong>先生成清单</strong><br>
报告会列出 target ID、风险、blocked 项和预计可回收空间。<br>
<em>List target IDs, risk, blocked items, and estimated reclaimable space.</em>
</td>
<td width="25%" valign="top">
<strong>避免误删</strong><br>
Downloads、Trash、Docker、hidden-home 等高风险项默认不会直接清。<br>
<em>Downloads, Trash, Docker, and hidden-home items are blocked by default.</em>
</td>
<td width="25%" valign="top">
<strong>方便复盘</strong><br>
输出 Markdown 或 JSON，路径默认脱敏，适合保存审计证据。<br>
<em>Markdown or JSON reports are redacted by default for review.</em>
</td>
</tr>
</table>

### 适合谁
### Who It Is For

- 普通 Mac 用户：想知道磁盘空间去哪了，但不想冒险乱删。  
  Mac users who want to understand storage usage without risky deletion.
- 开发者：经常被 Xcode、npm、pip、Gradle、CocoaPods、Homebrew、Playwright 或 IDE 缓存占空间。  
  Developers dealing with Xcode, npm, pip, Gradle, CocoaPods, Homebrew, Playwright, or IDE caches.
- Agent / Codex 工作流：需要“先列清单，确认后清理”的明确边界。  
  Agent and Codex workflows that need an explicit audit-before-clean boundary.

### 不适合什么
### What It Is Not For

- 不适合替你判断个人文件是否该删。  
  It will not decide whether your personal files should be deleted.
- 不适合跳过确认直接清敏感目录。  
  It will not skip confirmation for sensitive scopes.
- 不适合把系统目录当成默认清理范围。  
  It does not treat system directories as default cleanup scope.

## 近期更新
## Recent Notes

**最新更新 / Latest note**

- 更新时间：2026-05-05 20:31  
  Update time: 2026-05-05 20:31
- 更新内容：按人类阅读路径重排 README，补齐“解决什么问题、安装、三分钟上手、配置参数、常见问题”的主线。  
  Update content: Reorganized the README around the human reading path: problem, install, three-minute start, configuration, and FAQ.

**最近一条 / One recent note**

- 更新时间：2026-05-05 16:21  
  Update time: 2026-05-05 16:21
- 更新内容：继续精修 GitHub 首屏视觉，补了快速导航与“适合 / 不适合”信息块，让人类读者更快判断这个仓库该怎么用。  
  Update content: Further refined the GitHub first screen with quick navigation plus a fit-vs-not-fit panel so human readers can decide faster how to use the repo.

## 安装
## Installation

### 环境要求
### Requirements

| 项目 | 要求 |
| --- | --- |
| 系统 | macOS |
| Python | 建议 Python 3.10+；仓库当前用 Python 3.12 验证 |
| Python 依赖 | 无第三方依赖，只使用标准库 |
| Shell | `zsh` 或能执行 `bash` 命令的终端 |
| 可选工具 | `brew`、`docker`、`flutter`、`xcrun`；缺失时相关目标会跳过 |

| Item | Requirement |
| --- | --- |
| OS | macOS |
| Python | Python 3.10+ recommended; this repo is currently validated with Python 3.12 |
| Python packages | No third-party package; standard library only |
| Shell | `zsh` or a terminal that can run `bash` commands |
| Optional tools | `brew`, `docker`, `flutter`, `xcrun`; related targets are skipped when missing |

### 获取仓库
### Get the Repository

```bash
git clone https://github.com/Matoya-Amadeus/AISkill-MacStorageManager.git
cd AISkill-MacStorageManager
```

如果你用 ZIP 下载，也可以直接进入解压后的目录运行下面的命令。  
If you downloaded a ZIP, enter the extracted folder and run the commands below.

### 首次检查
### First Check

```bash
python3 --version
python3 scripts/mac_storage_manager.py --help
bash scripts/audit_storage.sh --help
```

`audit_storage.sh` 和 `safe_clean.sh` 在仓库里带可执行权限；如果 ZIP 下载后权限丢失，可以修一次：  
`audit_storage.sh` and `safe_clean.sh` are executable in the repo; if ZIP download removes that bit, fix it once:

```bash
chmod +x scripts/audit_storage.sh scripts/safe_clean.sh
```

## 三分钟上手
## Three-Minute Start

### 1) 只读审计：先看谁占空间
### 1) Read-only audit: see what uses space

```bash
bash scripts/audit_storage.sh
```

这一步不会删除文件。它会输出 Markdown 报告，包括 `Top Consumers`、`Cleanup Boundary`、`Cleaned / Planned` 和 `Next Step Options`。  
This does not delete files. It prints a Markdown report with `Top Consumers`, `Cleanup Boundary`, `Cleaned / Planned`, and `Next Step Options`.

### 2) 预演清理：看哪些会被清、哪些会被挡住
### 2) Preview cleanup: see what would clean or block

```bash
bash scripts/safe_clean.sh --dry-run
```

预演仍然不会删除文件。重点看每个 target 的状态：`planned`、`blocked`、`skipped`、`empty`。  
The preview still does not delete files. Look at each target status: `planned`, `blocked`, `skipped`, or `empty`.

### 3) 执行低风险清理
### 3) Apply low-risk cleanup

```bash
bash scripts/safe_clean.sh
```

`safe_clean.sh` 等价于：  
`safe_clean.sh` is equivalent to:

```bash
python3 scripts/mac_storage_manager.py clean --apply --yes --markdown
```

`--yes` 只会自动放行低风险目标。高风险目标仍然需要精确确认。  
`--yes` only unlocks low-risk targets. High-risk targets still need exact confirmation.

### 4) 高风险目标：必须使用 exact target ID
### 4) High-risk targets: use exact target IDs

先审计并找出真实 target ID：  
Audit first and find the real target ID:

```bash
python3 scripts/mac_storage_manager.py audit --include-hidden-home --markdown
```

然后把审计报告里的真实 `TARGET_ID` 填进去：  
Then use the real `TARGET_ID` from the report:

```bash
python3 scripts/mac_storage_manager.py clean \
  --apply \
  --include-hidden-home \
  --approved-targets TARGET_ID \
  --confirm-targets TARGET_ID \
  --markdown
```

不要猜 target ID。先看报告，再复制。  
Do not guess target IDs. Read the report, then copy the exact value.

## 常用场景
## Common Scenarios

### 我只想知道 Mac 空间去哪了
### I only want to inspect storage usage

```bash
python3 scripts/mac_storage_manager.py audit --markdown
```

想让脚本输出 JSON，方便其他工具处理：  
Use JSON output for another tool:

```bash
python3 scripts/mac_storage_manager.py audit --json
```

### 我只想安全清缓存和日志
### I only want to clean safe caches and logs

```bash
bash scripts/safe_clean.sh --dry-run
bash scripts/safe_clean.sh
```

默认会覆盖用户缓存、用户日志、常见开发缓存和可重建残留；个人文件类目标会被挡住。  
The default scope covers user caches, user logs, common dev caches, and regenerable leftovers; personal-file targets are blocked.

### 我想检查 hidden-home，比如 `~/.git`
### I want to inspect hidden-home items such as `~/.git`

```bash
python3 scripts/mac_storage_manager.py audit --include-hidden-home --markdown
```

hidden-home 是敏感范围。清理前必须先列清单，再传 `--approved-targets` 和需要的 `--confirm-targets`。  
hidden-home is sensitive. List first, then pass `--approved-targets` and the required `--confirm-targets` before cleanup.

### 我想排查某个 App 的残留
### I want to inspect leftovers for one app

```bash
python3 scripts/mac_storage_manager.py audit \
  --app-path "/Applications/Example.app" \
  --markdown
```

App leftovers 属于高风险目标，清理前需要精确确认。  
App leftovers are high risk and need exact confirmation before cleanup.

### 我想限制 Flutter 工程扫描范围
### I want to limit Flutter project scanning

```bash
python3 scripts/mac_storage_manager.py audit \
  --flutter-search-root "$HOME/Projects" \
  --markdown
```

### 我确实要看系统范围
### I really need to inspect system scope

```bash
python3 scripts/mac_storage_manager.py audit \
  --include-system \
  --system-roots /Library,/private/var/db/receipts,/private/var/tmp,/tmp \
  --markdown
```

系统范围默认关闭，且至少需要四个 system roots。不要把整台机器根目录 `/` 当成清理目标。  
System scope is disabled by default and requires at least four system roots. Do not use `/` as a cleanup target.

## 功能范围
## Cleanup Scope

### 默认会检查的低风险或可重建目标
### Default low-risk or regenerable targets

- `~/Library/Caches`、`~/Library/Logs`  
  User caches and logs.
- Xcode：`DerivedData`、`Archives`、`iOS DeviceSupport`、不可用模拟器。  
  Xcode `DerivedData`, `Archives`, `iOS DeviceSupport`, and unavailable simulators.
- 包管理器缓存：`npm`、`pnpm`、`pip`、`Gradle`、`CocoaPods`、Homebrew。  
  Package-manager caches: `npm`, `pnpm`, `pip`, `Gradle`, `CocoaPods`, and Homebrew.
- 开发工具缓存：Playwright、VS Code、JetBrains。  
  Dev-tool caches: Playwright, VS Code, and JetBrains.
- Flutter 工程残留：`build`、`.dart_tool`、iOS Pods、Android build 等。  
  Flutter project leftovers: `build`, `.dart_tool`, iOS Pods, Android build, and related generated files.

### 默认会阻止的目标
### Targets blocked by default

| Target | 风险 | 为什么挡住 |
| --- | --- | --- |
| `downloads` | high | 可能包含个人文件 |
| `trash` | medium | 可能仍有要恢复的文件 |
| `docker-prune` | high | `docker system prune -f` 不可恢复，并且只允许本地 Docker context |
| `home-dot-git` / `hidden-home:*` | high | hidden-home 可能包含凭据、仓库元数据或配置 |
| `app-leftovers:*` | high | App 残留匹配需要人工确认 |
| `system-*` | high | 系统范围默认不启用 |

| Target | Risk | Why it is blocked |
| --- | --- | --- |
| `downloads` | high | May contain personal files |
| `trash` | medium | May contain files you still need to restore |
| `docker-prune` | high | `docker system prune -f` is not recoverable and only local Docker context is allowed |
| `home-dot-git` / `hidden-home:*` | high | hidden-home may contain credentials, repo metadata, or config |
| `app-leftovers:*` | high | App leftover matching needs human review |
| `system-*` | high | System scope is not enabled by default |

## 安全模型
## Safety Model

<p align="center">
  <img src="assets/readme-workflow.svg" alt="Workflow from audit to list to approve to clean to verify" width="100%">
</p>

| 模式 | 是否删除 | 适合什么时候用 |
| --- | --- | --- |
| `audit` | 不删除 | 第一次查看空间热点和 target ID |
| `plan` | 不删除 | 看清理计划和 blocked 原因 |
| `clean --dry-run` | 不删除 | 用 clean 路径预演 |
| `clean --apply --yes` | 只清低风险 | 执行低风险清理 |
| `clean --apply --confirm-targets ID` | 按确认执行 | 处理需要确认的目标 |

| Mode | Deletes files | When to use |
| --- | --- | --- |
| `audit` | No | First inspection and target ID discovery |
| `plan` | No | Review cleanup plan and blocked reasons |
| `clean --dry-run` | No | Preview through the clean path |
| `clean --apply --yes` | Low risk only | Apply low-risk cleanup |
| `clean --apply --confirm-targets ID` | Confirmed scope only | Handle targets that require confirmation |

### 两个确认参数的区别
### Difference Between the Two Approval Flags

- `--approved-targets`：把目标加入批准清单，主要用于 hidden-home、system roots 等需要先列清单的范围。  
  `--approved-targets`: adds targets to the approved list, mainly for hidden-home, system roots, and scopes that must be listed first.
- `--confirm-targets`：确认某个需要人工确认的 target ID 可以执行。  
  `--confirm-targets`: confirms that a target requiring human approval may run.
- `--yes`：只对低风险目标生效，不会自动解锁高风险目标。  
  `--yes`: applies only to low-risk targets and does not unlock high-risk targets.

## 配置与参数
## Configuration & CLI Reference

### 命令入口
### Command Entrypoints

```bash
python3 scripts/mac_storage_manager.py audit [options]
python3 scripts/mac_storage_manager.py plan [options]
python3 scripts/mac_storage_manager.py clean [options]
```

Wrapper：  
Wrappers:

```bash
bash scripts/audit_storage.sh          # audit --markdown
bash scripts/safe_clean.sh --dry-run   # clean --apply --yes --markdown --dry-run
bash scripts/safe_clean.sh             # clean --apply --yes --markdown
```

### 常用参数
### Common Options

| 参数 | 作用 |
| --- | --- |
| `--home PATH` | 指定 home，默认当前用户 home |
| `--root PATH` | 指定扫描根目录，默认等于 home |
| `--days-to-keep N` | 只把超过 N 天的文件计入可清理，默认 7 |
| `--topk N` | 报告里显示前 N 个空间热点，默认 5 |
| `--json` | 输出 JSON |
| `--markdown` | 输出 Markdown |
| `--include-hidden-home` | 纳入 hidden-home 目标 |
| `--include-system` | 纳入 system 目标 |
| `--system-roots A,B,C,D` | 覆盖 system roots，至少四个路径 |
| `--flutter-search-root PATH` | 限制 Flutter 工程搜索范围 |
| `--app-path PATH` | 扫描某个 `.app` 的残留 |
| `--approved-targets ID1,ID2` | 指定批准清单 |
| `--confirm-targets ID1,ID2` | 精确确认目标 |
| `--apply` | clean 模式实际执行 |
| `--dry-run` | clean 模式预演 |
| `--yes` | 自动放行低风险目标 |

| Option | Purpose |
| --- | --- |
| `--home PATH` | Set home; defaults to current user home |
| `--root PATH` | Set scan root; defaults to home |
| `--days-to-keep N` | Count files older than N days as eligible; default 7 |
| `--topk N` | Show top N consumers; default 5 |
| `--json` | Print JSON |
| `--markdown` | Print Markdown |
| `--include-hidden-home` | Include hidden-home targets |
| `--include-system` | Include system targets |
| `--system-roots A,B,C,D` | Override system roots; at least four paths |
| `--flutter-search-root PATH` | Limit Flutter project search scope |
| `--app-path PATH` | Scan leftovers for one `.app` |
| `--approved-targets ID1,ID2` | Set approved target list |
| `--confirm-targets ID1,ID2` | Confirm exact targets |
| `--apply` | Actually run clean mode |
| `--dry-run` | Preview clean mode |
| `--yes` | Auto-approve low-risk targets |

### 环境变量
### Environment Variables

| 变量 | 作用 |
| --- | --- |
| `MAC_STORAGE_SYSTEM_ROOTS` | 不传 `--system-roots` 时，用它覆盖默认 system roots；逗号分隔 |

| Variable | Purpose |
| --- | --- |
| `MAC_STORAGE_SYSTEM_ROOTS` | Overrides default system roots when `--system-roots` is not passed; comma-separated |

## 报告怎么看
## How to Read the Report

- `Top Consumers`：当前最值得看的空间热点。  
  `Top Consumers`: the most relevant storage hotspots.
- `Cleanup Boundary`：清理必须遵守的边界。  
  `Cleanup Boundary`: boundaries the cleanup must obey.
- `Cleaned / Planned`：每个 target 的状态、风险和 blocked 原因。  
  `Cleaned / Planned`: status, risk, and blocked reason for each target.
- `Remaining Hotspots`：清理后或预演后仍然存在的热点。  
  `Remaining Hotspots`: hotspots remaining after apply or preview.
- `Next Step Options`：下一步建议。  
  `Next Step Options`: suggested next actions.

常见状态：  
Common statuses:

| 状态 | 含义 |
| --- | --- |
| `planned` | 预演中，尚未删除 |
| `ready` | apply 模式下可执行 |
| `cleaned` | 已执行清理 |
| `blocked` | 被安全规则挡住 |
| `skipped` | 缺路径、缺工具或条件不满足 |
| `empty` | 没有可清理内容 |

| Status | Meaning |
| --- | --- |
| `planned` | Previewed, not deleted |
| `ready` | Eligible during apply mode |
| `cleaned` | Cleanup executed |
| `blocked` | Blocked by safety rules |
| `skipped` | Missing path, missing tool, or unmet condition |
| `empty` | Nothing eligible to clean |

## 隐私与可移植性
## Privacy & Portability

- 报告默认把 home、root 和私有绝对路径脱敏。  
  Reports redact home, root, and private absolute paths by default.
- 容器 bundle ID 和 owner-mismatch path 会做敏感信息处理。  
  Container bundle IDs and owner-mismatch paths are sanitized.
- 脚本不硬编码用户名、机器名或固定设备路径。  
  Scripts do not hardcode usernames, machine names, or device-specific paths.
- `--system-roots` 和 `MAC_STORAGE_SYSTEM_ROOTS` 可以覆盖系统路径集合。  
  `--system-roots` and `MAC_STORAGE_SYSTEM_ROOTS` can override system paths.

## 开发者说明
## Developer Notes

### 目录结构
### Repository Layout

```text
README.md                         Human-facing guide
SKILL.md                          Agent-facing cleanup contract
scripts/mac_storage_manager.py     Core CLI engine
scripts/audit_storage.sh           Read-only Markdown audit wrapper
scripts/safe_clean.sh              Low-risk apply wrapper
tests/test_mac_storage_manager.py  Unit tests
references/hidden-home-cleanup.md  Sensitive-scope cleanup notes
templates/report.md                Report template
assets/                            README visuals
```

### 扩展方式
### How to Extend

清理目标在 `scripts/mac_storage_manager.py` 的 `StorageManager.discover_targets()` 中注册。新增目标时请先回答四个问题：  
Cleanup targets are registered in `StorageManager.discover_targets()` inside `scripts/mac_storage_manager.py`. Before adding one, answer four questions:

1. 这个目标是否可重建？  
   Is this target regenerable?
2. 风险是 `low`、`medium` 还是 `high`？  
   Is the risk `low`, `medium`, or `high`?
3. 是否需要 `requires_confirmation=True`？  
   Does it need `requires_confirmation=True`?
4. 是否必须先进入 `approved_targets`？  
   Must it require `approved_targets` first?

### 运行测试
### Run Tests

```bash
python3 -m unittest -v tests.test_mac_storage_manager
```

当前测试覆盖路径脱敏、敏感诊断脱敏、hidden-home 行为和自定义 system roots。  
Current tests cover path redaction, sensitive-note redaction, hidden-home behavior, and custom system roots.

---

由 **AI·Maho** 和 **人类·Matoya** 共同维护  
Maintained jointly by **AI·Maho** and **Human·Matoya**
