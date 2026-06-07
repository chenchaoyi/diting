# add-listening-mark-empty-state — design

## Context

Each list panel renders its waiting state by `update()`-ing a body
`Static` with one dim-italic line. Panels are event-driven — nothing
repaints them between poller updates, so an animation needs its own
timer. The design system rules say "Animation. Effectively none… the
scan cycle *is* the motion" and "the pixel-art beast is the only
mark. Do not redesign it."

## Goals / Non-Goals

**Goals:**

- A small, characterful waiting state for the four list panels using
  the existing mark, at negligible render cost.
- Honest motion: the pulse runs only while a sweep/scan is actually
  in flight.

**Non-Goals:**

- Animating any populated panel, the diagnostics panel, the events
  strip, or the brand header.
- New i18n strings, configuration, or a reduced-motion toggle (the
  animation is already absent in every state but "waiting + visible +
  unpaused"; snapshot captures land on frame 0 deterministically).
- Touching the mark's geometry (brand rule).

## Decisions

- **Diegetic pulse, mark untouched.** The beast renders exactly as
  the brand header's `_LOGO_MARK_ART`; the animation is a single dim
  `·` travelling away from the antenna on the antenna row — a radar
  wavefront, i.e. a picture of the sweep in progress. This reads as
  an extension of the "scan cycle is the motion" rule rather than a
  violation; the design README gets an explicit carve-out sentence so
  the system stays the source of truth.
- **Pure frame builder + dumb timer.** `_listening_mark(tick,
  caption)` is a pure function (tick → Rich Text), unit-testable
  without an app. Each panel owns one `set_interval(0.6, …,
  pause=True)` started paused on mount; the waiting-state path
  resumes it, the data path and `on_hide` pause it, and the tick
  no-ops (frame freeze) while `app._paused`. Pausing the Timer (not
  just no-opping) means a populated or hidden panel costs zero.
- **Frame 0 is the rest frame (no dot).** Deterministic first paint:
  snapshot regression captures and tests assert against frame 0
  without racing the timer.
- **Per-panel wiring over a shared widget.** The panels update a body
  `Static` in place (selection/click code paths depend on that
  widget); swapping in a mounted child widget would churn four
  panels' layout assumptions for no render-cost win. A tiny mixin
  (`_ListeningWait`) carries the timer/gating so the four panels
  share one implementation.

## Risks / Trade-offs

- [Animation timers leak repaints on populated panels] → the timer is
  hard-paused outside the waiting state; the tick handler also
  re-checks state defensively before painting.
- [Brand "no animation" drift] → carve-out documented in the design
  README itself; the pulse is one dim glyph at ≤2 Hz, frame-frozen on
  pause.
- [CJK/width regressions] → the art rows are plain Block Elements +
  ASCII dot, fixed 9–14 cells; no `pad_cells` interaction (no CJK in
  the art).
