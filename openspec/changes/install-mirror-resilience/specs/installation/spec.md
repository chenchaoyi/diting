## ADDED Requirements

### Requirement: The installer SHALL download via a validated mirror chain with GitHub as the trust anchor
When a GitHub Releases download fails (the chronic CN-network stall on `objects.githubusercontent.com`), the installer SHALL fall back through an ordered chain of mirror proxies rather than a single mirror, and SHALL validate the content of every downloaded asset before trusting it. GitHub Releases stays the canonical trust anchor; SHA256 verification of the tarball remains mandatory and unchanged.

**Mirror chain.** For a GitHub asset URL `U`, the candidate order under the default `auto` mode SHALL be: `U` (GitHub direct), then each proxy in the default chain applied as `<proxy>U`. The default chain SHALL be live proxies maintained in one place in the script; at time of writing `https://ghfast.top/`, `https://gh-proxy.com/`, `https://ghproxy.net/`. The dead `https://ghproxy.com/` SHALL NOT be in the chain. Each attempt keeps a bounded per-attempt timeout.

**Content validation.** An attempt SHALL count as successful only when the transfer succeeds AND the body is the expected kind of file:
- `SHASUMS256.txt` SHALL be accepted only if it contains a parseable checksum entry for the target tarball (a `<64-hex>` hash in the row whose second field is the tarball filename). An HTML page, empty body, or rate-limit stub returned with HTTP 200 SHALL be rejected.
- the tarball SHALL be accepted only if it is a valid gzip stream.

A rejected body SHALL be discarded and the next candidate tried. The step SHALL fail only when the whole chain is exhausted, with an error that reflects the real failure (chain exhausted / invalid content) rather than a misleading "missing entry".

**SHASUMS prefers GitHub-direct.** Under `auto`, `SHASUMS256.txt` SHALL always be attempted from GitHub-direct first regardless of where the tarball was obtained; a proxy SHALL serve `SHASUMS256.txt` only if GitHub-direct fails for it too. This narrows the window in which a single proxy could substitute a matching forged tarball+hash pair.

**Mirror selection grammar.** `DITING_INSTALL_MIRROR` SHALL accept:
- `auto` (default) — GitHub-first, then the proxy chain, with SHASUMS GitHub-first.
- `github` — GitHub only; no proxies.
- `ghproxy` — back-compat keyword; skip the GitHub-first attempt and use the proxy chain directly (for users who know GitHub is blocked).
- any value beginning with `http://` or `https://` — use it as the sole custom proxy prefix (e.g. a self-hosted gh-proxy), still GitHub-first under the `auto`-style ladder.

Any other value SHALL abort before downloading with a clear message naming the accepted forms.

**Honest trust notice.** When a proxy serves an asset, the installer SHALL surface a notice naming the proxy used, and the completion notice SHALL distinguish "tarball via mirror, SHASUMS direct from GitHub" (trust anchored on GitHub) from "SHASUMS also via mirror" (trust anchored on that mirror's bytes).

#### Scenario: GitHub fails, first live proxy in the chain serves the tarball
- **WHEN** the GitHub tarball URL fails and the first proxy returns the correct gzip bytes
- **THEN** the installer accepts the tarball from that proxy, proceeds to SHA verification, and the next proxies are not tried

#### Scenario: A dead proxy returning an HTML 200 is skipped, not fatal
- **WHEN** the GitHub URL fails and the first proxy returns HTTP 200 with an HTML landing page for `SHASUMS256.txt`
- **THEN** the installer rejects the HTML (no valid checksum entry), tries the next proxy, and succeeds when a later proxy returns a real `SHASUMS256.txt` — it does NOT die with "missing entry"

#### Scenario: Whole chain exhausted
- **WHEN** GitHub and every proxy fail or return invalid content for the tarball
- **THEN** the installer aborts non-zero at the download step with a message stating the chain was exhausted, naming the asset; no files are extracted

#### Scenario: SHASUMS taken from GitHub even when the tarball came from a proxy
- **WHEN** the tarball is served by a proxy but GitHub-direct succeeds for `SHASUMS256.txt`
- **THEN** `SHASUMS256.txt` is the GitHub-direct copy, the tarball is verified against it, and the completion notice states trust is anchored on GitHub

#### Scenario: Custom mirror via DITING_INSTALL_MIRROR URL
- **WHEN** the user runs `DITING_INSTALL_MIRROR=https://gh.example.test/ curl … | bash` and GitHub fails
- **THEN** the installer retries via `https://gh.example.test/<github-url>` and uses no other proxy

#### Scenario: Back-compat mirror keyword skips GitHub-first
- **WHEN** the user runs `DITING_INSTALL_MIRROR=ghproxy …`
- **THEN** the installer goes straight to the proxy chain for the tarball without the GitHub-first attempt, and still validates content

#### Scenario: Invalid mirror value aborts early
- **WHEN** `DITING_INSTALL_MIRROR=fastgit` is set
- **THEN** the installer aborts before any download with a message naming the accepted forms (`auto` / `github` / `ghproxy` / a URL)

#### Scenario: SHA256 verification still mandatory
- **WHEN** a tarball is obtained (from GitHub or any proxy) whose computed SHA256 does not match the validated `SHASUMS256.txt` entry
- **THEN** the installer aborts non-zero naming expected vs actual hash; no files are extracted
