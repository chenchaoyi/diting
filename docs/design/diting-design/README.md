# diting Design System

> *Your Mac hears more than it tells you.*

`diting` (谛听) is a single-window **macOS terminal listening post** for
Wi-Fi, BLE, link health, and the RF environment. It surfaces what
Apple's "Option-click Wi-Fi" panel hides — which AP you're glued to,
which BLE device is actually broadcasting, whether the upstream is
broken even when RSSI looks fine — through a Textual TUI rendered in
Fira Code over a near-black canvas with a single warm-orange brand
arc. The product is the terminal; this design system is what dresses
that terminal coherently across docs, marketing snapshots, status
modals, and any future surface (menu-bar app, Home-Assistant card,
docs site) that needs to feel like *the same instrument*.

This system stays deliberately small: **one mono typeface, a Monokai-
leaning semantic palette, a heavy orange box-drawing border, and a
content voice that sounds like an engineer who has read RFCs.** It
does not have rounded "card" components, gradients, or illustrations
— a TUI does not, so this brand does not either.

## Sources

- **Codebase:** `wifiscope/` (mounted via File System Access API).
  GitHub: [`chenchaoyi/wifiscope`](https://github.com/chenchaoyi/wifiscope).
  Python 3.11+, Textual TUI, CoreWLAN/CoreBluetooth backends, with a
  small Swift helper bundle for Location-Services-gated SSID/BSSID.
- **Snapshots:** `assets/snapshots/` — fixture renders of every TUI
  state (Wi-Fi main, BLE, Events modal, Help modal, Basics modal,
  redacted, disassociated, paused).
- **Logo:** `assets/logo.svg` — radar arcs + `diting` wordmark.
- **Examples:** `examples/aps.example.yaml` (AP-aliases config),
  `examples/CHANGELOG.md`.

The reader is not assumed to have access to the codebase — every
visual decision below is grounded in artefacts copied into this
project.

---

## CONTENT FUNDAMENTALS

The diting voice is the voice of someone who has spent too long
reading RFC 802.11 and would like you to know exactly what they will
and will not claim. Three things are always true of the copy:

### Tone

- **Direct, honest, unembellished.** No marketing softeners. The
  README opens *"You set up multiple APs at home or at the office,
  you walk between rooms, and your Mac stays glued to the AP it
  associated with five hours ago at -75 dBm — even though there's a
  new AP within reach broadcasting the same SSID at -45 dBm. Zoom
  stutters; you grumble; you blame the Wi-Fi."* That's the voice.
- **Numbers and protocol terms are first-class.** RSSI in dBm,
  channel widths in MHz, MCS / NSS / 802.11ax — diting never says
  "strong signal", it says `-58 dBm`. Use the same precision in any
  copy you write for this brand.
- **Honest about limits.** Diagnostics are called "a guide, not an
  RF survey tool". The Environment line is described as "Tier 0 of
  the Wi-Fi-sensing capability ladder" with an explicit "**NOT**
  Wi-Fi sensing" callout. If a capability stops short, say so.

### Person & casing

- **You-not-we, except in lists of capabilities.** Documentation
  addresses the user (`you walk between rooms`); release notes use
  imperative or system voice (`Open Wi-Fi Basics`, `Cycles Wi-Fi
  off/on`). The brand is `diting` — **always lowercase** in running
  prose and in the wordmark. Never `Diting`, never `DITING` (env
  vars use `DITING_` but that's shell, not voice).
- **Sentence case in UI.** Panel titles read `Connection`,
  `Nearby BSSIDs`, `Diagnostics`, `Roam log`. No Title Case, no
  ALL CAPS chrome. Inline tags read in brackets: `[ROAM]`, `[LINK]`,
  `[band switch on 2F-living]`.
- **No emoji, ever.** A Unicode glyph is allowed *only* when it's
  the most precise way to say what's happening: ↔ for sort cycle,
  ⚠ for an honest warning, σ for standard deviation, `▁▂▃▄▅▆▇█` as
  RSSI sparklines. Decorative emoji break the instrument feel.

### Vibe & examples

- **Footnote rather than oversimplify.** Wherever two readings
  could disagree, ship a footnote: `* Tx and Max use different
  CoreWLAN APIs and may diverge.`
- **Empty states are full sentences.** `(no APs from last scan —
  likely throttle, retrying)` · `(BLE diagnostics will appear after
  permission is granted)` · `(scanning...)`. Always parenthesised,
  always italic, always lowercase.
- **Headings can be wry.** README section titles are short, low-
  ceremony: `Why`, `Quick start`, `Bindings`, `macOS caveats`,
  `Roadmap`. Avoid gerund-titles ("Getting started"); prefer the
  blunt noun.

A line that captures the voice in a single string:
> *"Treat them as 'where to look next' hints rather than as Apple's
> official roaming decision."*

---

## VISUAL FOUNDATIONS

The product is a TUI, so the design system is a TUI grammar applied
elsewhere. Five principles cover almost everything:

1. **Box-drawing borders, not cards.** Every panel is a heavy 1px
   orange (`#fea62b`) frame with the title sitting on top of the
   border (the Rich `border_title` pattern). No drop shadows on
   panels, no rounded corners, no inner shadow gradients. The only
   rounded element in the whole system is the **macOS window
   chrome** (`border-radius: 8px`) that wraps the TUI in marketing
   shots.
2. **Near-black canvas.** Three greys do all the surface work:
   `#292929` (window), `#121212` (panel interior), `#1e1e1e`
   (footer / muted bands). `#262626` is reserved for alternating
   row highlights.
3. **One font.** Fira Code at 20px / 24.4px line-height is the
   default. Headings differ by colour and weight, never by family.
   When mono is genuinely wrong (e.g. running prose in long-form
   docs), fall back to the system UI stack — but don't ship two
   fonts in the same view.
4. **Semantic colour, not decorative.** Yellow means "warning /
   active", green means "ok / stable", red means "loss / error",
   cyan means "current AP / link / info", magenta means "ROAM".
   Never use these colours for chrome or hierarchy. The brand
   orange is reserved for borders, the radar arcs in the logo, and
   key glyphs.
5. **No imagery.** No photography, no illustrations, no gradients,
   no patterns. The only image asset that ships is the **logo**.
   Marketing surfaces use **TUI snapshots** (SVG-rendered with
   Textual's screenshot pipeline) as their hero — the product *is*
   the picture.

### Specifics, item by item

- **Backgrounds.** Solid fills only. No full-bleed images, no
  patterns, no gradients. The footer is a flat `#0178d4` blue band
  with `#ddedf9` text — that is the only colour-on-colour surface.
- **Animation.** Effectively none. The TUI repaints panels on a 7s
  scan cycle and a 1Hz latency cycle; that *is* the motion. Static
  surfaces (docs, marketing) get **no fades, no bounces, no
  parallax**. A prefers-reduced-motion-by-default brand.
  **One diegetic exception:** while a list panel is waiting on a
  sweep, the beast mark renders with a single radar pulse dot
  travelling from its antenna at ≤2 Hz — a picture of the sweep
  actually in flight, frame-frozen the moment polling pauses and
  gone the moment rows land. The mark's geometry is untouched.
- **Hover states.** A subtle background lift to `--bg-row-alt`
  (`#262626`); no colour-shift, no glow.
- **Press states.** Bound to keyboard shortcuts in the actual
  product, so the visual is the **keystroke shown in the footer**
  — `q quit`, `p pause`, `r force-rescan`. For HTML proxies,
  shrink the cell `transform: scale(0.98)` and snap back; no easing
  curve longer than 80ms.
- **Borders.** 1px heavy orange on panels; 1px `rgba(255,255,255,
  0.35)` on the macOS window outer; 1px `rgba(255,255,255,0.08)`
  on inner dividers. No double-borders, no dashed.
- **Shadow systems.** Two shadows, total: `--shadow-window` for the
  window chrome in marketing, `--shadow-modal` for the in-app
  modals. Panels never carry shadow.
- **Protection / capsules.** No protection gradients. Inline tags
  use a flat `#262626` capsule with bracketed text: `[ROAM]`,
  `[LINK]`. Tags never have rounded ends — they are square corners
  matching the box-drawing aesthetic.
- **Layout.** A single fixed full-window column on the TUI. Docs
  use a max-width of 720px for prose, 1200px for reference. The
  footer is **always pinned** to the bottom and **always shows the
  active key bindings** — no exceptions.
- **Transparency / blur.** Used in exactly one place: the macOS
  window chrome's outer `rgba(255,255,255,0.35)` border for the
  hairline. Backdrop blur is forbidden (it's not a TUI thing).
- **Imagery vibe.** Cool-leaning dark, 100% RGB, no grain, no
  photo treatment. If a real photo is ever needed (not currently),
  desaturate to ≤20% and tint with `--bg-panel`.
- **Corner radii.** `--r-sm: 2px` on chips and meters, `--r-lg:
  8px` on the macOS window only, `--r-pill: 999px` reserved for
  status dots. Panels get `0`.
- **Cards.** **There are no cards.** A panel is the only container
  — heavy 1px orange border, square corners, title sitting on the
  top edge. Anyone reaching for a rounded soft-shadowed card in
  this system is doing it wrong.

---

## ICONOGRAPHY

The product has almost no iconography in the traditional sense — a
TUI cannot render SVG. The system instead leans on three layers:

1. **Unicode box-drawing and glyphs.** `┏━━ Connection ━━━━━━┓`
   draws every panel border. Sparklines use `▁▂▃▄▅▆▇█`. Status uses
   `·`, `→`, `↔`, `⚠`, `σ`, `★`, `—`. These are not icons; they
   are part of the type stream. **Always Fira Code**, never an
   icon font.
2. **One SVG logo.** `assets/logo.svg` — three orange radar arcs
   at the lower-left anchored on a filled circle, followed by the
   `diting` wordmark in Fira Code SemiBold at 34px. Use this and
   only this for brand placement. Do not animate, recolor, or
   isolate the arcs from the wordmark.
3. **No icon font, no icon library.** The codebase ships zero PNG
   icons and zero SVG icons beyond the logo. **Do not import
   Lucide, Heroicons, or Material Symbols** into diting surfaces —
   their visual weight (rounded, soft-stroke, decorative) collides
   directly with the TUI grammar. If a non-TUI surface (a future
   web docs page, a menu-bar widget) genuinely needs an icon, use
   a **Unicode glyph at the surrounding text size and colour** as
   the first attempt. If that's impossible, hand-build a
   monospace-grid SVG (4×4 or 8×8 box-drawing style) at the brand
   orange, no fill, 1px stroke.
4. **Window chrome dots.** `#ff5f57 / #febc2e / #28c840` traffic-
   light circles in the macOS window header — these are decorative
   but ship as part of the snapshot frame, not as standalone icons.
5. **Emoji.** Never. See CONTENT FUNDAMENTALS.

---

## Index

Top-level files in this design system:

- `README.md` — this document. Voice, foundations, iconography.
- `colors_and_type.css` — CSS custom properties for every color,
  font, spacing, radius, shadow token, plus semantic styles
  (`h1`–`h4`, `code`, `.panel`, `.s-ok`, …) tied to them.
- `SKILL.md` — entry point for using this design system as an
  Anthropic / Claude Code skill.
- `assets/`
  - `logo.svg` — diting wordmark.
  - `snapshots/*.svg` — TUI fixture renders for marketing /
    documentation use. Drop in directly; do not crop.
  - `preview.svg`, `preview-ble.svg`, `preview-events.svg` — the
    three README-hero TUI shots.
- `fonts/` — Fira Code is loaded from CDN inside `colors_and_type.
  css`. **Substitution flagged:** the codebase references
  `'Fira Code', 'JetBrains Mono', 'SF Mono', Menlo, monospace`
  with `local()` first; we mirror that fallback chain. If you
  want offline-bundled woff2 files, drop them here and update the
  `@font-face` block — the licence (Fira Code, OFL) permits it.
- `examples/` — supplementary product copy reference
  (`aps.example.yaml`, `CHANGELOG.md`).
- `preview/` — design-system preview cards rendered for the
  Design System tab. Each is a single small HTML snippet.
- `ui_kits/tui/` — high-fidelity HTML recreation of the diting
  TUI. `index.html` walks through the Wi-Fi, BLE and Events
  views; the JSX components rebuild every panel.

## Caveats / substitutions

- **Fira Code** is loaded from cdnjs (the same source the codebase
  uses for SVG snapshot rendering). No `.ttf` is bundled in the
  repo, so we do the same. If you'd like Fira Code shipped offline,
  drop the woff2 files into `fonts/` — the `@font-face` rules in
  `colors_and_type.css` already declare a `local()` fallback.
- **No additional icon set.** The product has none, and we
  deliberately did not introduce one. If you discover a real
  iconography need, raise it before adding a library.
