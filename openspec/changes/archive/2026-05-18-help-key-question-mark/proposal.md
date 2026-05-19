## Why

User request (2026-05-18): rebind the in-app help screen from `h` to `?`. `?` is the long-standing convention for "what's here / how do I use this" across CLIs (`htop`, `less`, `vim`'s normal-mode help, etc.); discoverable by users who never read the footer label. `h` is freed up for a future per-view shortcut that wants it.

The change is purely a binding rename — no new behaviour, no new requirement on the help-screen content.

## What Changes

### `tui-shell` — help-screen modal binding moves from `h` to `?`
- **MODIFIED:** the help-screen modal SHALL open and close on `?` (named-key: `question_mark`) instead of `h`. The internal-close binding inside `HelpScreen.BINDINGS` is `escape,question_mark,q` (was `escape,h,q`). The visible footer-group label in the GroupedFooter Info group is `?` (was `h`). The hard-coded scroll-hint inside the help modal reads `Esc or ? to close`.
- The `h` key SHALL NOT be bound to any action; pressing `h` is a no-op so the slot is available for future bindings without colliding.
- All user-facing docs (README EN+ZH, modal body text "Info: `?` help · `b` basics") and tests SHALL reference `?` instead of `h`.

## Out of Scope

- Adding a `?` shortcut for sub-modal help (per-view contextual help). The single global help screen stays.
- Re-binding any other key.
- A migration banner / one-time hint about the rename. The footer label is the discovery surface; users who memorise key bindings will pick up `?` from the footer on next launch.
