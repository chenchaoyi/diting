## ADDED Requirements

### Requirement: The installer SHALL attempt GitHub first and fall back to `ghproxy.com` for tarball + SHASUMS downloads, with the SHA-verification chain unchanged
`install.sh` SHALL download both the release tarball and the `SHASUMS256.txt` checksum file via a two-step ladder: `github.com/.../releases/download/<tag>/<file>` first; on curl failure or `--max-time 20` timeout, `https://ghproxy.com/https://github.com/.../releases/download/<tag>/<file>` second. Both downloads SHALL apply `curl -fsSL --max-time 20 --output <dest>`; the SHA256 verification step SHALL continue to validate against `SHASUMS256.txt` regardless of which URL served the bytes.

The installer SHALL honour `DITING_INSTALL_MIRROR={auto,github,ghproxy}` as an env override:

- `auto` (default, or unset): GitHub-first ladder, ghproxy fallback.
- `github`: GitHub only; on failure the existing `die_with_marker` site fires unchanged.
- `ghproxy`: ghproxy only; skip the GitHub-first attempt entirely. CN users who already know GitHub will time out can use this to avoid the 20 s wait per install.
- Any other value SHALL cause `install.sh` to fail at startup with `die "unknown DITING_INSTALL_MIRROR value: <value> (expected auto|github|ghproxy)"`.

When the fallback fires for EITHER the tarball OR the `SHASUMS256.txt` download (i.e. ghproxy.com served at least one of the two), `install.sh` SHALL print one informational notice line after the verify step succeeds: in EN `tarball or SHASUMS fetched via ghproxy.com mirror; trust anchored on SHA256`; in ZH `tarball 或 SHASUMS 通过 ghproxy.com 镜像下载；信任仍锚定于 SHA256`. The notice fires through the existing `note` helper so it renders correctly under TIER LOG / PLAIN / FULL.

When ghproxy.com is also unreachable (or when `DITING_INSTALL_MIRROR=github` was set and GitHub failed), `install.sh` SHALL fail at the existing `die_with_marker <step_n> …` site with a message naming BOTH attempted URLs so the user can debug network reachability.

The installer SHALL NOT chain to additional mirrors beyond ghproxy.com — a single fallback host keeps the failure mode auditable. If ghproxy.com goes down for an extended period, the response is to ship a new `install.sh` pointing at a different mirror, not to add a third hop on every install.

The installer SHALL NOT add region detection. The GitHub-first ladder is correct for every region: global users get the direct GitHub path on first try (no proxy hop, no third-party dependency); CN users where GitHub fails get the automatic fallback. No locale / IP-geolocation / language preference influences mirror selection.

The installer SHALL NOT add `--insecure` / `-k` to the fallback curl call. TLS validation against `ghproxy.com`'s certificate stays mandatory; a hostile-mirror MITM is detected and the install aborts.

#### Scenario: Global user with healthy GitHub connectivity (default `auto`)
- **WHEN** a US/EU user runs the curl-bash one-liner and the GitHub tarball download completes successfully within 20 s
- **THEN** the install proceeds with bytes from GitHub directly; the "fetched via ghproxy.com mirror" notice does NOT print; the SHA256 verification fires unchanged

#### Scenario: CN user where GitHub stalls (default `auto`)
- **WHEN** a CN user runs the one-liner and the GitHub tarball download fails (curl non-zero exit, e.g. `--max-time 20` exhausted on a stalled connection)
- **THEN** `install.sh` prints `note "GitHub download failed (likely CN network); retrying via ghproxy.com mirror..."` and retries via `https://ghproxy.com/<url>`; on success the install proceeds and the "fetched via ghproxy.com mirror" notice prints on completion

#### Scenario: Both primary and fallback fail
- **WHEN** GitHub returns curl-failure AND ghproxy.com also returns curl-failure within their respective 20 s budgets
- **THEN** `install.sh` SHALL fail at the existing `die_with_marker 3 …` site for the tarball or `die_with_marker 4 …` for the shasums, with a message naming both attempted URLs; exit code is 1 (unchanged from pre-change `die` semantics)

#### Scenario: `DITING_INSTALL_MIRROR=ghproxy` skips the GitHub-first attempt
- **WHEN** the user runs `DITING_INSTALL_MIRROR=ghproxy bash install.sh`
- **THEN** `install.sh` SHALL try `https://ghproxy.com/<github-url>` first and only; if ghproxy fails the install fails with the existing `die_with_marker` site (no fallback to GitHub since the user explicitly opted out of that path)

#### Scenario: `DITING_INSTALL_MIRROR=github` enforces the canonical-only path
- **WHEN** the user runs `DITING_INSTALL_MIRROR=github bash install.sh`
- **THEN** `install.sh` SHALL try the GitHub URL only and on failure fall through to the existing `die_with_marker` site without attempting ghproxy.com; pre-v1.8.0 behaviour is byte-identical for this case

#### Scenario: Invalid `DITING_INSTALL_MIRROR` value
- **WHEN** the user runs `DITING_INSTALL_MIRROR=fastgit bash install.sh`
- **THEN** `install.sh` SHALL fail at startup before any download attempt with `die "unknown DITING_INSTALL_MIRROR value: fastgit (expected auto|github|ghproxy)"`; exit code is 1

#### Scenario: SHA verification against ghproxy-served bytes
- **WHEN** the tarball downloaded via the ghproxy.com fallback completes and the SHA256 of those bytes is computed
- **THEN** the SHA SHALL be compared against the `SHASUMS256.txt` content (whichever URL served that file); if they match the install proceeds; if they mismatch the install aborts with the existing `die_with_marker 4 "sha256 mismatch …"` site

#### Scenario: ZH-locale notice for the mirror-fired path
- **WHEN** a ZH-locale user (`DITING_LANG=zh` or macOS preference resolving to zh) triggers the fallback path
- **THEN** the completion notice prints in Chinese: `tarball 或 SHASUMS 通过 ghproxy.com 镜像下载；信任仍锚定于 SHA256`; the EN-locale equivalent fires for any other locale
