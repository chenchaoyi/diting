# Document the `tui-shell` capability

## Why

The four-panel layout, the in-place view-toggle, and the
GroupedFooter convention are conventions every other capability spec
implicitly assumes. Pinning them protects against well-meaning
refactors — e.g. a contributor switching from `display = False` to
mount/unmount would silently break the test suite's widget-tree
queries; a contributor flattening the GroupedFooter back to default
Textual Footer would make the eight bindings less discoverable.

## What Changes

- Introduce capability `tui-shell`.
- No code changes — backfill from the App / panel / modal classes
  in `src/wifiscope/tui.py`.

## Capabilities

### New Capabilities
- `tui-shell`: panel layout invariant, view-toggle mechanic, modal
  open/close lifecycle, footer grouping, hidden-binding policy,
  subtitle live-update contract.

### Modified Capabilities
None.

## Impact

- Affected code: none (documentation-only)
- Affected specs: creates `openspec/specs/tui-shell/spec.md`
- Cross-cuts with: every other capability that renders into a
  panel (`wifi-scanning`, `bluetooth-scanning`, `link-health`,
  `environment-monitor`, `events`, `ble-detail-modal`)
- Future impact: any structural change to the panel order or
  the modal-stack contract MUST file a MODIFIED Requirement
