## ADDED Requirements

### Requirement: The subtitle SHALL include a scene chip
The `BrandHeader`'s subtitle line (rendered from `App.sub_title` / `_build_subtitle()`) SHALL include the active scene as a short chip alongside the existing view name and scan-interval indicator. The chip uses dim styling consistent with the rest of the subtitle.

Format (EN):

```
view: Wi-Fi · scan 7s · [home]
```

Format (ZH):

```
视图：Wi-Fi · 扫描间隔 7s · [家]
```

The chip text is the scene name in the active locale (EN catalog: `home` / `office` / `public` / `audit`; ZH catalog: `家` / `公司` / `公共` / `排查`). The square brackets are part of the format and are NOT locale-dependent.

The subtitle SHALL re-render when the active view or scan interval changes; the scene chip itself never changes during a session (scene is fixed at startup), but it MUST be re-rendered with the subtitle to remain visible after each refresh.

#### Scenario: EN home scene chip
- **WHEN** `diting --scene home` is launched in an EN locale
- **THEN** the subtitle reads `view: Wi-Fi · scan 7s · [home]`

#### Scenario: ZH office scene chip
- **WHEN** `diting --scene office --lang zh` is launched
- **THEN** the subtitle reads `视图：Wi-Fi · 扫描间隔 7s · [公司]`

#### Scenario: Audit scene visible in title
- **WHEN** `diting --scene audit` is launched
- **THEN** the subtitle includes `[audit]` (EN) or `[排查]` (ZH) — a fast visual indicator that all gating is disabled
