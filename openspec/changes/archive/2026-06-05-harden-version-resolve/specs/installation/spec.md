# installation — delta

## MODIFIED Requirements

### Requirement: The installer SHALL fetch the matching release tarball from GitHub Releases and verify its SHA256
The installer SHALL download the platform-matching tarball from the project's GitHub Releases and SHALL refuse to proceed when the SHA256 does not match the published hash. For each supported arch (`darwin-arm64`, `darwin-x86_64`) a GitHub Release SHALL provide:

- `diting-X.Y.Z-darwin-{arch}.tar.gz` — the platform tarball
- `SHASUMS256.txt` — a sibling asset listing SHA256 hashes for
  each tarball, one per line, in `sha256sum`-compatible format

The installer SHALL resolve the latest release via the GitHub API
(`api.github.com/repos/chenchaoyi/diting/releases/latest`) with a bounded
timeout; when the API attempt fails, it SHALL fall back to following the
`https://github.com/<repo>/releases/latest` redirect through the same
candidate chain used for asset downloads (GitHub-direct first, then the
mirror proxies), reading the version tag from the redirect's final URL
(`…/tag/<version>`). A tag parsed from the redirect SHALL be accepted only
when it matches a version shape (optional `v` + leading digit). When every
resolution path fails, the installer SHALL abort with guidance naming both
escapes — `DITING_VERSION=vX.Y.Z` to skip resolution, and
`DITING_INSTALL_MIRROR` for the asset mirrors. The installer SHALL then
download the right tarball, compute its SHA256, and abort if the hash does
not match the `SHASUMS256.txt` entry.

Version resolution does not move the trust anchor: it only selects *which*
tag to fetch; the tarball is still verified against a `SHASUMS256.txt`
that is attempted GitHub-direct first.

The README (EN + ZH) SHALL document the bootstrap mirror form for networks
where `raw.githubusercontent.com` itself is blocked (the script cannot help
before it runs): prefixing the raw script URL with a chain proxy, e.g.
`curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash`.

#### Scenario: Tarball matches SHASUMS256.txt
- **WHEN** the download completes and the computed SHA256 matches the entry in SHASUMS256.txt
- **THEN** the installer proceeds to extract and install

#### Scenario: Tarball SHA256 mismatch
- **WHEN** the computed SHA256 does NOT match the recorded entry
- **THEN** the installer aborts with a non-zero exit and stderr message naming the expected vs actual hash; no files are extracted

#### Scenario: Tag-locked install via DITING_VERSION env var
- **WHEN** the user runs `DITING_VERSION=v0.10.0 curl … | bash`
- **THEN** the installer fetches `v0.10.0` specifically rather than the latest tag

#### Scenario: API blocked, redirect fallback resolves the version
- **WHEN** `api.github.com` is unreachable but the `releases/latest` redirect succeeds (direct or via a chain proxy)
- **THEN** the installer resolves the version from the redirect's final `/tag/<version>` URL and proceeds to the download step

#### Scenario: Resolution fails everywhere with actionable guidance
- **WHEN** the API and every redirect candidate fail
- **THEN** the installer aborts non-zero with a message naming `DITING_VERSION` to pin a version and `DITING_INSTALL_MIRROR` for mirrors

#### Scenario: A non-version redirect is rejected
- **WHEN** a proxy answers the `releases/latest` redirect with a final URL that does not end in a version-shaped `/tag/<version>`
- **THEN** that candidate is rejected and the next one tried
