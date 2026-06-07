# add-panel-zoom-and-scope-reroam — design

## Context

The app is a single vertical stack (header / connection / diagnostics
/ one-of-four list panels / events / footer). The list panel gets
whatever vertical space is left — often ~10 rows — while a dense
environment produces 30–80 BLE rows or 20+ scan groups. Events solved
the same problem with the `m` modal browser (`EventsScreen`), but that
is a snapshot modal with its own renderer; cloning that pattern for
four list panels would duplicate each panel's rendering and break
live-update/selection behaviours users already have.

`c` (Re-roam) is bound at App level and rendered unconditionally in
the footer's Scan/view group, so it looks and acts global even though
it only makes sense against the Wi-Fi link.

## Goals / Non-Goals

**Goals:**

- Full-screen reading of whichever list view is active, without
  losing live updates, sort, selection, or inspect.
- `c` visible and active only where it is meaningful (Wi-Fi view).

**Non-Goals:**

- Zooming the connection / diagnostics / events panels (events
  already has `m`; the others are fixed-height summaries).
- Persisting zoom state across restarts.
- Touching the events modal.

## Decisions

- **Use Textual's built-in `Screen.maximize(widget)` / `minimize()`**
  (available in the pinned Textual 8.2.5) instead of a new modal
  screen. The maximized widget is the live panel itself: pollers keep
  painting it, `s` sort and `up`/`down`/`enter` keep dispatching on
  it, and the implementation is one action + bookkeeping rather than
  four new screens. Alternative — an `EventsScreen`-style snapshot
  modal per panel — rejected: 4× renderer duplication, dead data while
  open, and a second selection model to maintain.
- **`z` as the key, "Zoom" / 「放大」 as the label.** Mnemonic in EN,
  unambiguous in ZH, and free (q/p/r/s/n/c/m/?/b/k/P/i are taken).
  Footer shows it in the Scan/view group on every view.
- **Esc also restores.** Textual 8.2.5 ships no default Esc→minimize
  binding, so the App binds Esc to minimize, gated by
  `check_action` to "a panel is currently maximized" — it must not
  shadow Esc inside modal screens (modals sit above the default
  screen, whose maximize state is independent).
- **`n` keeps the zoom.** `action_toggle_view` re-maximizes the newly
  visible panel when the previous one was maximized — the user asked
  to read lists large; bouncing back to the cramped layout on every
  view cycle would defeat that.
- **Scope `c` via `check_action` + conditional footer entry.**
  `check_action("reroam")` returns False off-Wi-Fi (disables the key
  AND hides it from the command palette); `GroupedFooter.
  refresh_layout` already re-renders on view toggle, so the entry
  just becomes conditional on `view_mode == "wifi"`. The help modal
  marks the binding Wi-Fi-only.

## Risks / Trade-offs

- [A maximized panel hides the connection/diagnostics context] → that
  is the point of zoom; one keypress (`z`/Esc) restores, and the
  subtitle/header stay visible.
- [Textual maximize interacts with `display=False` siblings] → the
  maximized panel is always the visible one; `action_toggle_view`
  minimizes before flipping `display` flags and re-maximizes after,
  so the maximize target is never a hidden widget.
- [`z` pressed while a modal is open] → `check_action` gates zoom to
  the default screen, so modal keymaps are unaffected.
