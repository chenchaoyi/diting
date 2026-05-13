# 发布 diting

如何 cut 一个新版本，让 curl-bash 一行命令能装上。

> 英文版镜像：[`docs/RELEASE.md`](../RELEASE.md)。任何一边的修改都必须
> 在同一个 PR 里同步另一边。

## 发布产物

每个 tag 对应 GitHub Release 上的三个 asset：

| Asset | 由谁构建 | 谁消费 |
|---|---|---|
| `diting-X.Y.Z-darwin-arm64.tar.gz` | matrix job `macos-14` | install.sh（Apple Silicon） |
| `diting-X.Y.Z-darwin-x86_64.tar.gz` | matrix job `macos-13` | install.sh（Intel） |
| `SHASUMS256.txt` | 两个 matrix 跑完后的 `shasums` job | install.sh 的 SHA 校验 |

每个 tarball 含一个 PyInstaller 冻结后的 `diting` 二进制 + Swift
helper bundle 副本（`diting-tianer.app`）。结构：

```
diting-X.Y.Z/
├── bin/diting             # 相对 symlink → libexec/diting/diting
├── libexec/diting/        # PyInstaller --onedir 输出
│   ├── diting
│   └── _internal/
└── share/diting-tianer.app/
```

## 切一个发布

1. **改版本号。** 修改 `pyproject.toml` 的 `version = "X.Y.Z"`，
   再 `uv sync` 刷新 `uv.lock`。在 `main` 上提交——按 v0.9.0 起
   的 CHANGELOG 策略，release notes 是 release 时从 OpenSpec
   archive 派生，不再每 PR 维护。

2. **打 tag。**
   ```bash
   git tag -a vX.Y.Z -m "release X.Y.Z"
   git push origin vX.Y.Z
   ```
   tag 推送会触发 `.github/workflows/release.yml`。

3. **盯 workflow。** 两个 matrix job（`macos-14` 与 `macos-13`）各
   自构建 helper、冻结 Python binary、跑
   `scripts/package_release.sh`、把 tarball + `.sha256` sidecar 上
   传到 release。`shasums` job 等两边跑完后，用 `gh release
   download` 拉回来，跑 `sha256sum`，把汇总好的 `SHASUMS256.txt`
   作为 sibling asset 传上去。

4. **在干净环境冒烟。** 在干净 macOS 账号（或没有源码树的 Mac）
   上跑：
   ```bash
   DITING_VERSION=vX.Y.Z curl -fsSL https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash
   diting --help
   diting
   ```
   首次启动应该弹「定位服务」与「蓝牙」授权对话框。

5. **更新 GitHub Release 文案**（Web UI）。从
   `openspec/changes/archive/<since-last-tag>/` 拉相关 proposals
   里的 bullets，分组为「新增 / 变更 / 修复 / 移除」。

## 手动 / 干跑构建

要在不打正式 tag 的情况下验证冻结 binary 构建，用
`workflow_dispatch` 手动触发：

- Actions 标签页 → **release** → **Run workflow**
- 把 `version` 填成例如 `v0.10.0-rc1`
- tarball 会作为 workflow artifact 上传（**不**是 release asset），
  便于单独 inspect。

本地 arm64-only 干跑：

```bash
uv sync --group release
bash scripts/package_release.sh 0.10.0-rc1
# 产出 dist/diting-0.10.0-rc1-darwin-arm64.tar.gz
```

## 排查

- **PyInstaller 漏了某个 pyobjc framework。** 在
  `scripts/build_frozen.py` 里再加一行 `--collect-all
  pyobjc_framework_<Name>`。冻结后 binary 第一次启动遇到缺
  framework 会 import 报错——这是补全 `--collect-all` 的信号。

- **install.sh 跑完 Gatekeeper 警告还在。** 确认
  `xattr -dr com.apple.quarantine` 跑成功了（可以再手动跑一次清掉
  装好的 bundle 的 xattr）。长期方案是 install 计划的 Phase 3：
  Apple Developer 签名 + 公证。在此之前同一 cdhash 只会弹一次警
  告——重装相同版本不会再触发。

- **`macos-13` runner 退役。** GitHub 终将下线 Intel 托管 runner。
  到那时要么把 x86_64 构建迁到当时最新的 x86_64 runner，要么
  直接放弃 x86_64（截止 2026 年 Apple Silicon 在新 Mac 中占比已
  >70%）。
