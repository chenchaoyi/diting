---
name: diting-design
description: Use this skill to generate well-branded interfaces and assets for diting (wifiscope), either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping the macOS Wi-Fi/BLE TUI.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.

Quick orientation:
- `colors_and_type.css` — every token (colors, type, spacing, radii, shadows) plus base semantic styles. Always include it on any artefact.
- `assets/logo.svg` — the only brand mark. Use whole; never split arcs from wordmark.
- `assets/snapshots/*.svg` — TUI fixture renders. Use as marketing hero / docs imagery instead of inventing illustrations.
- `ui_kits/tui/` — high-fidelity HTML recreation of the TUI, with React JSX components for every panel.
- `preview/*.html` — small specimen cards covering colors / type / spacing / components / brand.

Voice rules in one line: lowercase brand `diting`, you-not-we, exact protocol terms (RSSI in dBm, MCS/NSS, σ), no emoji, parenthesised italic empty states, one footnote rather than oversimplify.

Visual rules in one line: heavy 1px orange border on near-black panels, square corners, Fira Code only, semantic colour (green/yellow/red/cyan/magenta) used strictly by role, no cards, no shadows on panels, no illustrations.
