<sub>[English](../workflow.md) · **中文**</sub>

# Diting 开发流程

一个改动从想法走到合入主干的全过程。简而言之：新分支 → 起 spec
change → 实现 → 自测 → CI → 评审 → 归档。任何一步漏掉，PR 不合入。

> **中英文同步**：本文档对应英文版
> [`docs/workflow.md`](../workflow.md)。任何一边的修改都必须在同一个
> PR 里同步另一边。

## 分支策略 — 强制新分支

每个改动**必须**走分支，不允许直接 commit 到 `main`。从最新的
`main` 切分支：

| 前缀 | 用于 |
|---|---|
| `feature/<name>` | 新能力或扩展 |
| `fix/<name>` | 缺陷修复 |
| `refactor/<name>` | 内部清理，无可观察行为变更 |
| `chore/<name>` | 工具链 / 依赖 / 不改 `openspec/` 的纯文档变更 |

分支名简洁、有描述性、kebab-case（`feature/eddystone-decoder`、
`fix/airpods-modal-crash`）。PR 模板会让你确认分支是从最新 `main`
切出的；评审者会检查。

`main` 出问题需要紧急修时也走 `fix/`，不能直接 push。分支生命周期
越短越好——长寿命的 feature 分支意味着痛苦的 rebase。

## 单 change 的 spec 流程（OpenSpec）

每个会改变可观察行为的分支都带一个 OpenSpec change。整个流程接到了：

- `openspec` CLI（npm `@fission-ai/openspec`，全局装一次：
  `npm install -g @fission-ai/openspec`）
- Claude Code 的 `/opsx:propose` / `/opsx:apply` / `/opsx:sync` /
  `/opsx:archive` / `/opsx:explore` slash 命令，落在
  `.claude/commands/opsx/`

可以走 CLI、可以走 Claude Code slash 命令、也可以手写 Markdown——
格式简单到工具只是辅助，不是必需。

### 1. Propose（起草）

Claude Code 里最快的路径：

```
/opsx:propose <kebab-name 或一句描述>
```

它会在 `openspec/changes/<name>/` 建好骨架：`.openspec.yaml` +
`proposal.md` / `design.md` / `tasks.md` / `specs/<capability>/spec.md`。

CLI 路径：

```bash
openspec new change <kebab-name>
# 然后手填四个文件
```

每个 change 含四个文件：

| 文件 | 内容 |
|---|---|
| `proposal.md` | **Why** + **What Changes** + **Capabilities** (New / Modified / Removed) + **Impact**（影响的文件、依赖） |
| `design.md` | 关键决策、否决方案、风险 |
| `tasks.md` | 实施 checklist（PR commit 推进时勾选） |
| `specs/<capability>/spec.md` | spec **delta** —— `### ADDED Requirement: ...`、`### MODIFIED Requirement: ...`、`### REMOVED Requirement: ...` |

如果改动跨多个 capability，在 `specs/` 下每个 capability 一个目录。

如果是纯文档改动（给已有代码补 spec），change 名用
`document-<capability>`，并在 `proposal.md` 引用源文件。

### 2. 实现

`tasks.md` 的勾选随 commit 推进。代码在 `src/`，测试在 `tests/`。
push 前本地跑一遍 `uv run pytest`。

### 3. Merge

PR 合入 `main`。测试必须全绿；spec delta 要能干净 apply 到
canonical `openspec/specs/`（review 会看 delta diff）。

### 4. 归档

merge 后把 spec delta apply 到 `openspec/specs/<capability>/spec.md`，
再把 change 目录搬到 archive。

Claude Code 里：

```
/opsx:archive <change-name>
```

CLI：

```bash
openspec archive <change-name>
```

两种都做：
- `ADDED Requirement: …` → 追加到 canonical（去掉 ADDED 前缀）
- `MODIFIED Requirement: …` → 替换匹配条目
- `REMOVED Requirement: …` → 移除匹配条目
- 把 `openspec/changes/<change-name>` 移到
  `openspec/changes/archive/<YYYY-MM-DD>-<change-name>/`

canonical specs 成为新的 source of truth；archive 保留历史。一个
change 目录绝不会同时存在两边。

归档前可以校验：

```bash
openspec validate <change-name> --strict
```

## Capability 与 change 的关系

- **Capability** = 长期存在的行为契约。落在
  `openspec/specs/<capability>/spec.md`。change 落地时它会更新，
  但不会"消失"。
- **Change** = 一个离散的工作单元。有起点（`proposal.md`）和终点
  （归档时的时间戳）。多个 change 可以反复修改同一个 capability。

当前所有 capability 索引在
[`openspec/README.md`](../../openspec/README.md)。

## 测试

三层，全部进 CI：

| 层 | 工具 | 位置 |
|---|---|---|
| 单元 | pytest | `tests/test_<module>.py` |
| TUI 烟雾 | pytest + Textual `app.run_test` | `tests/test_tui_smoke.py` |
| 快照回归 | `scripts/tui_snapshot.py --mode regression` | `snapshot-output/` |

`live_*` 类的快照场景（`--mode explore`）只能在真机上跑，不进 CI。

### 测试设计纪律

`tests/TESTING.md` 是 diting 的**权威测试方案**——每条自动化测
试都对应那份文档里的一行。改动测试面时的顺序：

1. 先改 `tests/TESTING.md`（英文版 + 中文镜像
   `docs/zh/TESTING.md`）——用文字描述新的 / 改的场景。
2. 把文字翻译成 pytest 用例。
3. 跑一遍看它失败，写产品代码，再跑一遍看它通过。

**只加测试不改 `tests/TESTING.md` 是文档化的 review 拦截项。**

### Spec ↔ test 映射

`openspec/specs/<name>/spec.md` 里的每个 capability 都有对应的
test 文件（或现有文件里的一节）。spec 加一个带 Scenario 的
Requirement 时，那个 Scenario 必须出现在测试里。反过来也是：测试
断言了任何 spec 里没有的行为是"信号"——要么这个行为值得起一个
spec（提一个 `openspec/changes/document-<capability>`），要么测试
过度规定了实现细节。

### push 前必跑的自测

PR 打开前严格按这个顺序：

```bash
uv run pytest                                                    # 0 失败
uv run python scripts/tui_snapshot.py --mode regression          # 0 断言失败
openspec validate --specs --strict                               # 15/15 通过
openspec validate <你的change> --strict                          # 当前 change 通过
```

任何一步红了，PR 就不要开。CI 会跑这四关；本地先跑省一轮 CI 反馈。

### 用 subagent 跑测试

`/opsx:test`（Claude Code slash 命令）把这一整套自测交给一个子
agent 去跑，结果以"通过/失败"摘要回到主线程，避免测试日志污染父
agent 的上下文。在测试时间长、或者你想让父 agent 一边等结果一边
干别的事时很有用。

## 本地常用命令

```bash
uv run pytest                                              # 完整单元 + 烟雾
uv run python scripts/tui_snapshot.py --mode regression    # 合成回归
uv run python scripts/tui_snapshot.py --mode explore       # 真机环境，/tui-audit
openspec validate --specs --strict                         # 校验 canonical specs
openspec list                                              # 在飞 changes
openspec view                                              # 仪表盘
```

## CI 强制项

`.github/workflows/test.yml` 在每次 PR 与 push 到 `main` 时跑：

- **pytest** — Python 3.11 / 3.12 / 3.13 矩阵
- **regression** — `tui_snapshot.py --mode regression`，断言失败时
  上传 `snapshot-output/` 作为 artifact
- **spec-validation** — `openspec validate --specs --strict` 和
  active changes（如有）的 strict 校验

任何一项失败都不能 merge。

## PR 标准

PR 模板（`.github/pull_request_template.md`）会自动填上结构。
检查项：

- [ ] 分支名符合规范，且从最新 `main` 切出
- [ ] OpenSpec change 已建（`openspec/changes/<name>/` 含
  proposal / tasks / specs delta）
- [ ] `openspec validate <name> --strict` 本地通过
- [ ] 单元测试针对新行为补齐
- [ ] `tests/TESTING.md` 与 `docs/zh/TESTING.md` 同步更新
- [ ] `/opsx:test` 子 agent 跑过且全绿
- [ ] CI 全绿（pytest 矩阵 + regression + spec validation）
- [ ] README 与 `docs/zh/README.md` 同步更新（如果用户面变了）
- [ ] EN ↔ ZH parity 守住：`i18n.py` 改字串两边都改；
  `docs/*.md` 改了就改 `docs/zh/*.md`
- [ ] `CHANGELOG.md` 与 `docs/zh/CHANGELOG.md` `[Unreleased]` 段都
  更新
- [ ] merge 后已 `/opsx:archive <name>`

## 合并策略

- 默认 **squash merge**，commit 信息引用 change 名
- merge 后立刻删除远端分支
- 不允许 force-push 到 `main`

## CHANGELOG + 中英文双语文档

`CHANGELOG.md` 保留面向用户的发布说明（英文）。每个会发布用户
可见行为的 change 在 `[Unreleased]` 段加一行，引用 change 名供
读者 drill into archive。中文镜像 `docs/zh/CHANGELOG.md` 必须在
同一个 PR 里同步。

### 中英文双语规则（EN ↔ ZH parity）

中文受众是 diting 的一等公民；丢中文的 change 是不完整的。在
一个 PR 里：

- `i18n.py` 每改一个 EN 键，必须同时改对应的 ZH 值。
- `docs/<file>.md` 每改一次都要带 `docs/zh/<file>.md` 的对应改动
  （现有文件：`README.md`、`TESTING.md`、`HELPER.md`、
  `CHANGELOG.md`、`workflow.md`、…）。
- README 用户面 section 改动时，要同步改 `docs/zh/README.md`。
- 新加 help/basics 模态文案，必须 EN 源 + `_ZH` 同行落。文件结构
  让这一步很自然。

PR 模板的 "Docs" 段会让你确认 parity；目前 CI 不强制 lint，但
review 会拦。后续 `feature/lint-bilingual-parity` 可以把这步自
动化。

## 什么时候**不**走 OpenSpec 流程

- 纯 CHANGELOG / README / 截图修改 → `chore/` 分支即可，不需要
  `openspec/changes/` 条目。
- 紧急修复挂掉的 CI → `fix/` 分支，先把 build 救绿；如果这次
  fix 编码了一个值得保留的契约，事后再补一个
  `document-<capability>` change。
- `/tmp/` 下的实验脚本、`scripts/<name>_spike.py` —— 那些不是
  契约。如果实验毕业成正式能力，再补正式 capability + spec。
