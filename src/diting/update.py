"""Self-update for the installed `diting` binary.

`diting update` resolves the latest GitHub release, compares it with the
running version, and (unless `--check`) re-runs the canonical one-line
installer pinned to that version — so the frozen binary AND the Swift
helper bundle both refresh through the single source of truth (`install.sh`),
rather than this module re-implementing download / verify / extract.

Network calls go through `urllib` (no third-party deps in the frozen
binary). Everything here is import-light and side-effect-free at module
load so `diting --version` / `capabilities` stay fast.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

# Same repo + install URL the README documents. `DITING_REPO` mirrors the
# installer's override so tests (and forks) can retarget.
REPO = os.environ.get("DITING_REPO", "chenchaoyi/diting")
LATEST_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SH_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"

_UA = "diting-update"


def normalize(version: str) -> str:
    """Strip a leading `v` so `v2.0.5` and `2.0.5` compare equal."""
    return version[1:] if version.startswith("v") else version


def version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted version into an int tuple for ordering. The
    pre-release suffix (`-rc1`, `+build`) is dropped; non-numeric
    components degrade to 0 rather than raising."""
    core = normalize(version).split("-")[0].split("+")[0]
    out: list[int] = []
    for part in core.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def is_newer(latest: str, current: str) -> bool:
    """True iff `latest` orders strictly after `current`."""
    return version_tuple(latest) > version_tuple(current)


def fetch_latest_tag(*, timeout: float = 10.0) -> str:
    """Return the latest release tag (e.g. `v2.0.5`) from the GitHub API.
    Raises on network / parse failure so the caller can report it."""
    req = urllib.request.Request(
        LATEST_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
        data = json.load(resp)
    tag = data.get("tag_name")
    if not tag:
        raise RuntimeError("releases/latest response had no tag_name")
    return tag


def run_installer(tag: str, *, lang: str | None = None,
                  timeout: float = 30.0) -> int:
    """Fetch `install.sh` and run it via `bash -s`, pinning `DITING_VERSION`
    to `tag` so the install resolves to exactly the version we reported (no
    re-resolution race). Returns the installer's exit code. The installer
    owns download / verify / extract / helper-prime / setup, so a `diting
    update` refreshes the binary and the helper bundle the same way a fresh
    install does."""
    req = urllib.request.Request(INSTALL_SH_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        script = resp.read()
    env = dict(os.environ)
    env["DITING_VERSION"] = tag
    if lang:
        env["DITING_LANG"] = lang
    proc = subprocess.run(["bash", "-s"], input=script, env=env)
    return proc.returncode
