# Harden installer version resolution + document the bootstrap mirror

## Why

A real CN-corporate-network install attempt died at the very first byte:

```
curl: (35) LibreSSL SSL_connect: SSL_ERROR_SYSCALL in connection to raw.githubusercontent.com:443
```

The mirror chain shipped in v1.9.x hardened the **asset** downloads (tarball +
SHASUMS), but two earlier steps still assume a working GitHub path:

1. **Fetching `install.sh` itself** (`raw.githubusercontent.com`) — fails
   before the script runs, so no script logic can save it. The README's
   mirror section documents asset mirrors but never says how to fetch the
   script when raw.githubusercontent.com is blocked.
2. **Resolving the latest version** (`api.github.com/.../releases/latest`) —
   a bare `curl` with no timeout, no mirror fallback. On the same networks
   that block raw, `api.github.com` fails too, and the install dies at
   "could not resolve latest release" even though the mirror chain right
   below it could have served everything.

## What Changes

- **Version resolution gets the mirror treatment.** Try the GitHub API first
  (bounded timeout). On failure, walk the existing candidate chain for
  `https://github.com/<repo>/releases/latest` and read the redirect's final
  URL — it ends in `/tag/<version>`, which proxies relay unchanged. The
  parsed tag must look like a version (`v?digit…`) to be accepted.
- **Resolution failure says what to do next.** The error now names both
  escapes: `DITING_VERSION=vX.Y.Z` to skip resolution, and
  `DITING_INSTALL_MIRROR` for the asset path.
- **README (EN + ZH) documents the bootstrap mirror** — when fetching
  `install.sh` itself fails (the SSL reset above), prefix the raw URL with a
  chain proxy:
  `curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/chenchaoyi/diting/main/install.sh | bash`

No trust-model change: version resolution determines *which* tag to fetch;
the tarball SHA256 verification against a GitHub-first SHASUMS is unchanged.
A lying proxy at the resolve step can at worst point at a different *real*
release (assets for a fabricated tag would 404 chain-wide).

## Impact

- Affected specs: `installation` (the fetch-and-verify requirement's
  resolution sentence + new scenarios).
- Affected code: `install.sh` (`resolve_latest_version` + error copy),
  `README.md` + `docs/zh/README.md` (bootstrap mirror note).
- Tests: fake-`curl` PATH shims in `tests/test_install.py` exercising the
  redirect fallback and the failure guidance.
