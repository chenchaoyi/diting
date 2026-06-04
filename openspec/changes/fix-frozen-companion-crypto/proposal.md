# Fix frozen-binary crash on the companion screen (missing _cffi_backend)

## Why

The shipped (PyInstaller-frozen) `diting` binary crashes and exits the moment
the user opens the companion screen (`k`) — or otherwise touches the companion
crypto path — with:

```
ModuleNotFoundError: No module named '_cffi_backend'
```

Root cause: the companion-bridge secretbox path imports PyNaCl
(`from nacl.secret import SecretBox`) **lazily** — nothing on the startup / hot
path touches it unless the user pairs or opens the companion screen. PyInstaller's
static analysis starts at the entry stub and follows imports, so it never reaches
`nacl`; the frozen bundle therefore ships no `nacl`, no bundled libsodium, and —
fatally — no `_cffi_backend` (the C extension PyNaCl's cffi binding loads at
runtime via `import _cffi_backend`). Everything works until the companion path
runs, then it hard-crashes. This makes the entire companion bridge (pairing,
insight/threat forwarding) unusable from a release build.

`build_frozen.py` already `--collect-all`s the other lazy / data-bearing
packages (pyobjc bridges, textual, rich, zeroconf, ifaddr) for exactly this
reason; PyNaCl was simply never added.

## What Changes

- `scripts/build_frozen.py`: add `--collect-all nacl`, `--collect-all cffi`, and
  `--hidden-import _cffi_backend` to the PyInstaller command, so the frozen
  bundle carries PyNaCl's `_sodium` ext + libsodium dylib + cffi + the
  `_cffi_backend` C extension. Verified: a fresh frozen build now contains
  `_internal/_cffi_backend.cpython-311-darwin.so` + `_internal/nacl/_sodium.abi3.so`,
  and `dist/diting/diting companion status` runs clean (exit 0) instead of
  crashing.
- The PyInstaller argv is extracted into a `_pyinstaller_cmd()` function so a
  unit test can assert the collection flags stay present without running a full
  frozen build (CI only does the frozen build on a release tag).

## Impact

- Affected specs: `installation` (the frozen binary must run the lazy-imported
  companion crypto path without a missing-native-module crash).
- Affected code: `scripts/build_frozen.py`; `tests/test_build_frozen.py` (new
  guard).
- **The currently-installed v1.14.0 binary is already broken** — this fix only
  reaches users via a new release. Recommend a **v1.14.1** hotfix. Until then the
  workaround is to run `uv run diting …` from the repo (the dev venv has cffi) or
  avoid the companion screen.
- Dev (`uv run`) is unaffected — cffi is installed in the venv, so the crash was
  frozen-build-only.
