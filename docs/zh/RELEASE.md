# 发布 diting

如何 cut 一个新版本，让 curl-bash 一行命令能装上。

> 英文版镜像：[`docs/RELEASE.md`](../RELEASE.md)。任何一边的修改都必须
> 在同一个 PR 里同步另一边。

## 发布产物

每个 tag 对应 GitHub Release 上的这些 asset：

| Asset | 由谁构建 | 谁消费 |
|---|---|---|
| `diting-X.Y.Z-darwin-arm64.tar.gz` | `macos-14` runner（原生） | install.sh（Apple Silicon） |
| `diting-X.Y.Z-darwin-x86_64.tar.gz` | `macos-14` runner 上 Rosetta 2 | install.sh（Intel） |
| `<arch>.tar.gz.sha256`（×2） | `package_release.sh`（每 arch 一份） | sidecar，由 `shasums` job 汇总 |
| `SHASUMS256.txt` | 两个 arch 都构建完后的 `shasums` job | install.sh 的 SHA 校验 |

两种 arch 都从**同一个** `macos-14`（arm64）runner 上构建。Swift
helper 只编译一次，产出 universal2 binary（单个 Mach-O 里同时包含
arm64 与 x86_64 两个 slice），两份 tarball 都用这同一个 helper。
PyInstaller 冻结的 Python 是 arch-specific，所以分两次构建：arm64
走原生，x86_64 走 Rosetta 2（`arch -x86_64`）。完整顺序见
`.github/workflows/release.yml` 里的 `build` job。

每个 tarball 含一个 PyInstaller 冻结后的 `diting` 二进制 + 一份
universal2 的 Swift helper bundle（`diting-tianer.app`）。结构：

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

3. **盯 workflow。** 单个 `build` job 在 `macos-14` 上产出两种
   arch：一次性构建 universal2 helper，arm64 原生跑 PyInstaller，
   再走 Rosetta 2 跑 x86_64。两个 tarball + 各自的 `.sha256`
   sidecar 一起上传到 release。`shasums` job 跑完后用
   `gh release download` 拉回来跑 `sha256sum`，把汇总好的
   `SHASUMS256.txt` 作为 sibling asset 传上去。

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

- **`macos-13` runner 队列。** 从 v1.0.8（2026-05-13）起 workflow
  完全不再用 `macos-13`。两种 arch 都在一个 `macos-14`（arm64）
  runner 上构建；helper 改成 universal2，冻结 Python 跑两次（原生
  + Rosetta）。如果 GitHub 以后连 arm64 托管 runner 都退役，把
  workflow 指向当时最新的 `macos-N` arm64 即可；只要苹果还发
  Rosetta，Rosetta 那步就还能用。

- **升级用户在新版本安装后又被询问了一次定位与蓝牙授权。** 这是预期
  行为——helper bundle 的 cdhash 变了，macOS TCC 按 cdhash 锚授权。
  bundle 里增删任意文件（比如 v1.0.x 第一次加入 `AppIcon.icns`）都
  会导致 cdhash 变化。同一版本之后在相同路径再次安装则保留授权。
  发版 notes 中应明确告知这一变化。

- **curl 装的 `diting` 卡在「需要以下权限：定位服务」而
  `uv run diting` 正常**。这就是 v1.0.7 修过的 macOS 26
  TCC-vs-LaunchServices 不对称问题。如果哪天回退（比如把 helper 的
  `scan` 子命令简化回单一直接 exec subprocess），这个症状会复发。
  验证修复仍在的脚本：
  ```bash
  rm -rf ~/Library/Application\ Support/diting/diting-tianer.app
  cp -R helper/diting-tianer.app ~/Library/Application\ Support/diting/diting-tianer.app
  pkill -f diting-tianer; sleep 10
  ~/Library/Application\ Support/diting/diting-tianer.app/Contents/MacOS/diting-tianer scan \
    | python3 -c "import sys,json;n=json.load(sys.stdin)['networks'];print(f'with_bssid={sum(1 for r in n if r.get(\"bssid\"))}')"
  ```
  必须打印 `with_bssid=>0`。若打印 `with_bssid=0`，说明
  `helper/Sources/diting-tianer/main.swift:runScanAndDumpJSON` 里的
  LaunchServices outer/inner 拆分被破坏了。完整背景见函数顶部注释
  —— macOS 26 上 direct-exec subprocess 不继承 bundle 的 Location
  TCC 授权，必须通过 `/usr/bin/open` 重启自己才能被
  LaunchServices 正确归属。
