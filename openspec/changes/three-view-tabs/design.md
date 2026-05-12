## Context

PR #30 added the third Bonjour panel and the 3-way `n` cycle.
Functional but invisible: only the active view is visible at any
moment, and the only hint at the alternatives is the footer's
`→ Next` breadcrumb. The audit (2026-05-12 16:26) confirmed: a user
who toggles to BLE and stops never learns that Bonjour exists.

Today the third-slot panel uses `border_title` to render a
short status string (e.g., `Nearby BSSIDs (104) · sort: AP`). The
`border_subtitle` slot is unused.

Textual's border-title supports Rich markup, so we can style per-
character — bold/cyan for the active view, dim for the others.

The four polish items are independent of the main change but ride
in the same PR for cohesion.

## Goals / Non-Goals

**Goals:**

- Three view names visible from every screen, so a user discovers
  the full set in one glance.
- Active view is unambiguously marked.
- Zero new screen rows — reuse the existing border chrome.
- Detail content (count / sort hint) preserved, just moved to the
  border subtitle so it stays readable.
- The four post-merge polish items shipped alongside.

**Non-Goals:**

- **No tab-bar widget**. A separate row above the panel would
  duplicate the affordance and waste a screen row.
- **No clickable tabs**. The `n` key cycles; mouse-click-to-switch
  is a future concern.
- **No abbreviated tab labels** ("WF/BL/BJ"). Full names ("Wi-Fi",
  "BLE", "Bonjour") read cleaner.
- **No animation / transition**. Synchronous swap, same as today.
- **No tab indicator on the other panels** (Connection /
  Diagnostics / Events). Those don't toggle.

## Decisions

### Tab indicator goes in `border_title`, detail goes in `border_subtitle`

Textual renders `border_title` at the top-left edge of the frame
and `border_subtitle` at the bottom-right. Putting the tab list at
the top is the most natural place — that's where the user looks
first when checking which panel they're on.

Title content (Rich markup):

```
 [bold cyan]Wi-Fi[/]  ·  [dim]BLE[/]  ·  [dim]Bonjour[/]
```

Active mode swaps the markup styles. Markup is computed once per
view-toggle by a shared helper:

```python
def _view_tabs_border_title(active: str) -> str:
    parts = []
    for mode in ("wifi", "ble", "mdns"):
        label = _view_display_name(mode)
        if mode == active:
            parts.append(f"[bold cyan]{label}[/]")
        else:
            parts.append(f"[dim]{label}[/]")
    return "  ·  ".join(parts)
```

The three `_refresh_*_panel` callers set:

```python
panel.border_title = _view_tabs_border_title(self._view_mode)
panel.border_subtitle = <the panel-specific detail>
```

### Display-name map for the subtitle and tab labels

Replaces today's `t(self._view_mode)`:

```python
_VIEW_DISPLAY_NAMES = {
    "wifi": "Wi-Fi",
    "ble": "BLE",
    "mdns": "Bonjour",
}

def _view_display_name(mode: str) -> str:
    return _VIEW_DISPLAY_NAMES.get(mode, mode)
```

Used in three places:
- Tab indicator labels in the border title.
- Header subtitle (`view: Bonjour`).
- Footer's `n  → <next>` label (already uses a similar map in
  `GroupedFooter.refresh_layout`; merge the two into one source).

Internal `_view_mode` token stays `mdns` — only the user-facing
display changes.

### `service types` i18n key fix

Today:
- Call site (`tui.py:_bonjour_diagnostic_lines`):
  `t("  ·  {n} service types", n=...)`.
- Catalog (`i18n.py`): `"{n} service types": "{n} 种服务"`.

The two don't match — `t()` falls through to the source string.

Fix: drop the leading separator from the call site. The separator
is already part of how the diagnostic line composes; build it
explicitly:

```python
line.append(t("  ·  "), style="dim")
line.append(t("{n} service types", n=len(services)), style="dim")
```

Or simpler — fold the separator into a positional argument
upstream so the catalog key is clean.

### Bonjour name suffix strip

Service-instance names per RFC 6763 are of the form
`<friendly-name>.<service-type>.local.`. Example announced by macOS:

```
ccy MBP2024 M4 Office._airplay._tcp.local.
```

The trailing `._airplay._tcp.local.` is redundant with the adjacent
Services column. Strip during render — not in `BonjourPoller`
(the full name stays in the data for forward-compat with future
features like notify-on-disappear).

Helper:

```python
def _strip_service_suffix(name: str, service_type: str) -> str:
    suffix = "." + service_type.rstrip(".") + "."
    if name.endswith(suffix):
        return name[: -len(suffix)]
    suffix = "." + service_type.rstrip(".")
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name
```

Applied in `_bonjour_row_line` before passing to `fit_cells`.

## Risks / Trade-offs

- **Risk**: tab labels eat title row width on narrow terminals.
  Three labels (`Wi-Fi`, `BLE`, `Bonjour`) plus separators = ~20
  cells. Textual centres / truncates titles. On terminals < 70
  cells this might shrink the title to drop the right-most label.
  → **Mitigation**: the title is just decoration; the active mode
  is still encoded in the panel content + footer. Degradation
  is graceful.

- **Risk**: Textual border-title Rich-markup rendering varies by
  border style. The `heavy` border (current) accepts markup; the
  `round` border may have different padding rules.
  → **Mitigation**: snapshot regression catches visible drift.

- **Trade-off**: the subtitle now carries content. If the panel
  height is very short the subtitle could overlap with the top
  of the next panel. Modal screens / small terminals are the
  risk surface.
  → **Acceptance**: the subtitle is a single line on the bottom
  border; it doesn't take a body row. Should be fine.

- **Risk**: the merged BLE / Bonjour list is short — only 3 rows in
  test data — so the title-tab approach looks busy relative to
  the body. On real-data captures (50+ BLE devices, 100+ Wi-Fi
  BSSIDs) the proportion feels right.

## Migration Plan

1. Cut `feature/three-view-tabs-and-mdns-polish` (done).
2. Phase A: OpenSpec scaffolding (this set of artifacts).
3. Phase B: implement
   - `_view_display_name()` + `_VIEW_DISPLAY_NAMES`.
   - `_view_tabs_border_title()` helper.
   - Three `_refresh_*_panel` updates (border title + subtitle).
   - `_build_subtitle()` uses display name for the view part.
   - Bonjour suffix-strip helper + integration into row renderer.
   - Catalog fix for `service types`.
   - Tests + TESTING.md + CHANGELOG.
4. CI gates.
5. PR.
6. After merge: `openspec archive three-view-tabs`.

Rollback: revert the merge commit.

## Open Questions

- **Tab label separator**: `Wi-Fi · BLE · Bonjour` with middle-dots
  is the cleanest. Alternatives: `[Wi-Fi] [BLE] [Bonjour]` (brackets
  feel like checkboxes), `Wi-Fi | BLE | Bonjour` (pipe is too
  heavy). Going with `·`.
- **Active marker**: bold cyan vs underline vs bracketed. Bold cyan
  matches diting's existing emphasis vocabulary (Roam Score "GOOD"
  / "WEAK" use the same palette). No reason to invent new style.
