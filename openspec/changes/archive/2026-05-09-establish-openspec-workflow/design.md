# Design — establish OpenSpec workflow

## Decisions

### Use OpenSpec format (same as StreetEye), not a custom one

We considered three options:

1. **Keep the per-release brief approach** at `docs/specs/v0.x.0-*.md`.
   Pro: zero migration cost. Con: doesn't scale to multi-capability
   PRs, no capability index, no diff-friendly delta unit. **Rejected.**
2. **Use `architecture decision records` (ADRs) à la Nygard**.
   Pro: well-known. Con: ADRs are decision records, not behaviour
   contracts. They drift from code over time and don't give us a
   queryable "what does the system promise" surface. **Rejected.**
3. **Use OpenSpec as in `~/StreetEye`**.
   Pro: maintainer already runs this format on a sibling project; tool
   surface is consistent across both repos; the SHALL / WHEN / THEN
   contract style is exactly right for a tool that claims observability
   guarantees. Con: yet-another-format relative to vanilla docs.
   **Accepted.**

### Skip the OpenSpec CLI dependency for now

StreetEye uses `@fission-ai/openspec` (Node) for `openspec validate`
and `openspec archive`. Wifiscope is a pure Python project and adding
a Node toolchain just for spec validation is a real cost (CI image,
contributor onboarding). The format is plain Markdown; humans can
write and review it without tooling. If validation churn proves
expensive later, we can add the Node CLI as a dev dependency or
write a tiny Python validator.

### Companion archive changes for backfill, not a single mega-change

Six backfilled capabilities × one archive change each = six small,
reviewable historical units. The alternative (one mega-change adding
all the specs at once) is faster to write but the future archive
reader sees a 2000-line diff with no story. Per-capability archive
changes match how the code actually evolved: each capability landed
as its own piece of work, even if the doc didn't follow.

### Archive entries even though no PR review happened

Some lint-style spec workflows say "if it didn't go through a PR, it
shouldn't be in the archive." We're being pragmatic: the backfill is
real work that captures the contract that *was* implicitly enforced
all along. Archive entries with `proposal.md` explaining the
documentation-only nature, plus `tasks.md` showing the spec was
extracted from specific source files, gives future readers the
provenance they need.

## Risks

- **Drift between specs and code**. The classic SDD risk. Mitigation:
  every code change that touches a spec'd capability MUST file a
  change with a delta. Reviewers gate this — no `openspec/specs/`
  edits outside of a change archive.
- **Spec rot in old archive entries**. Once archived, the historical
  proposal / design / tasks files are frozen. If we discover a bug
  in the documented contract later, the fix goes through a NEW
  change with a MODIFIED Requirement, not an edit to the archive.
- **Capability boundary disputes**. Two contributors might draw
  capability boundaries differently (e.g. is "BLE detail modal" its
  own capability, or part of `bluetooth-scanning`?). Conventions
  in `openspec/AGENTS.md` resolve this — capabilities are
  *behaviour contracts*, so anything with externally observable
  behaviour stable enough to write SHALL statements about deserves
  its own spec. Fine-grained beats coarse.

## Why these specific six capabilities for the initial backfill

The MVP backfill picks the six most load-bearing capabilities — the
ones where contract drift would silently break the tool's promises:

- **`macos-helper`** — the foundation. Every other capability depends
  on the helper bundle's TCC + schema + subprocess contract.
- **`wifi-scanning`** — the original raison d'être of wifiscope.
- **`bluetooth-scanning`** — the BLE side, schema-4 raw passthrough.
- **`ble-decoders`** — just established this week; pinning the
  framework contract before more decoders pile in.
- **`ble-detail-modal`** — also new this week; pinning the modal /
  selection contract before more keybindings layer on.
- **`link-health`** — gateway/WAN ping aggregates, which the events
  ring + analyze + JSONL log all depend on.

Capabilities NOT in the initial backfill (deferred to follow-on
`document-*` changes once the workflow proves out):
`environment-monitor`, `events`, `event-log`, `analyze`, `i18n`,
`inventory`, `roam-detection`, `tui-shell`, `cli`. These are real
capabilities; their specs just don't have to land in the same
turn.
