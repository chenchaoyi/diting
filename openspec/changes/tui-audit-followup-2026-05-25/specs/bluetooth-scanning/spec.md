## ADDED Requirements

### Requirement: The BLE row renderer SHALL substitute `(rotating ID)` for high-entropy local names while preserving the raw value in the detail modal
The BLE row renderer SHALL substitute the locale-stable placeholder `(rotating ID)` for any device whose advertised local name matches a high-entropy rotating-identifier shape, and SHALL preserve the raw value verbatim in the BLE detail modal. The substitution is render-only; the underlying `BLEDevice.name` field SHALL NOT be mutated.

Apple Continuity (Find-My / Handoff / Nearby-Info) and some IoT vendors (Huami / Amazfit / Mi-Band) publish opaque rotating-identifier strings in the BLE local-name slot — for example `NZ1NhvIw3H5T5cSy3kULrJ` (Apple Continuity) or `Z-GM0YXG6A` (Huami serial). These are not human-readable identities and reading them as device names is misleading.

The row renderer SHALL apply a `_looks_like_rotating_id(name)` predicate to the `name` field. The predicate SHALL return `True` if and only if ALL of the following hold:

- `name` is non-empty
- `name` contains no whitespace characters (`\s` per Python regex)
- `name` matches `^[A-Za-z0-9+/=_-]{16,}$` (16+ characters, base64 / hex / underscore / hyphen alphabet only)
- `name` does NOT start with any of: `iPhone`, `iPad`, `Mac`, `AirPods`, `HomePod`, `Apple TV`, `Apple Watch`, `Beats` (case-insensitive prefix match)

When the predicate returns `True`, the row's `name` column SHALL render the locale-stable string `(rotating ID)` (EN catalog) / `(临时标识)` (ZH catalog) in dim italic style — the same style class used for `(anonymous)` / `(unknown)`. The underlying `BLEDevice.name` field SHALL NOT be mutated; the substitution is purely a render-time transform.

The BLE detail modal SHALL surface the raw advertised string under a new `Raw name:` row (EN) / `原始名称:` row (ZH) in the Identity section *whenever the row's display value would differ from the raw helper value* — that is, whenever `_looks_like_rotating_id(d.name)` returns `True`. Users investigating a specific device can still see exactly what the helper reported. The row SHALL be omitted when `BLEDevice.name` is None or empty, and SHALL be omitted when the list already renders the raw value (predicate returned `False`) — the Identity section's existing `name:` row already carries it.

#### Scenario: Apple Continuity rotating identifier
- **WHEN** the helper emits a row with `vendor="Apple, Inc."`, `name="NZ1NhvIw3H5T5cSy3kULrJ"`, no `device_class`
- **THEN** the list row's name column renders `(rotating ID)` in dim italic, AND the detail modal's Identity section includes a `Raw name: NZ1NhvIw3H5T5cSy3kULrJ` row

#### Scenario: Huami serial-shaped name
- **WHEN** the helper emits a row with `vendor="Huami"`, `name="Z-GM0YXG6A"`
- **THEN** the list row's name column renders `(rotating ID)`; the detail modal still surfaces `Raw name: Z-GM0YXG6A`

#### Scenario: Real Apple device prefix is preserved
- **WHEN** the helper emits a row with `name="iPhone"` or `name="ccy iPhone 15 Pro Max"`
- **THEN** the predicate returns `False`; the list row's name column renders the original string; no `Raw name:` row is added to the detail modal (because the list value already matches)

#### Scenario: Short or whitespaced names are preserved
- **WHEN** the helper emits a row with `name="HW Watch GT"` or `name="abc"`
- **THEN** the predicate returns `False` (contains whitespace / fewer than 16 chars); the list row renders the original string

#### Scenario: Connected peripheral with a real device name
- **WHEN** the helper's `retrieveConnectedPeripherals` snapshot lists a Magic Keyboard with `name="ccy's Magic Keyboard"`
- **THEN** the predicate returns `False` (contains whitespace + apostrophe); the connected-section row renders the original string verbatim

#### Scenario: Raw-name row in ZH catalog
- **WHEN** the user runs `DITING_LANG=zh diting` and opens the detail modal on an Apple rotating-ID row
- **THEN** the detail modal's Identity section shows `原始名称: NZ1NhvIw3H5T5cSy3kULrJ` (label from the ZH catalog; value verbatim)
