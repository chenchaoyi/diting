## Context

`service_category(uuid, *, category_only=False)` in
`src/diting/ble.py:563` is the single resolver for the BLE list's
"Services" column AND the BLE diagnostic strip's "Categories" row.
The two callers want different things:

- **Services column** (per-row): "given a device's UUIDs, label
  what it can do". `Device Information` here is legitimate — it
  tells the user this device exposes the standard SIG `Device
  Information` GATT service (firmware version, model number,
  manufacturer string).
- **Categories row** (aggregate): "given everything around me,
  what kinds of devices are these?". `Device Information` here
  is noise — it counts essentially every BLE device that supports
  bonding, which is most of them, and inflates a top-of-list
  number that reads as a device-class label.

`service_category` already has a `category_only=True` switch that
the Categories row uses. The switch currently only filters out
the member-UUID layer (so vendor names like `Xiaomi Inc.` don't
appear as "kinds"). It does NOT filter the GATT-services layer.
This change adds that second filter.

## Goals / Non-Goals

**Goals:**

- Categories diagnostic stops counting `1800` / `1801` / `180A` as
  device kinds.
- Per-row Services column still resolves those three UUIDs to
  their human-readable names.
- A reviewable spec Requirement that a future contributor would
  find before re-introducing the same bug.

**Non-Goals:**

- **Don't curate a full "device-class-meaningful GATT services" allowlist.**
  The reverse approach — only allow specific UUIDs into Categories
  — is open-ended (Heart Rate, HID, Audio, Battery, Environmental
  Sensing, Glucose Monitor, Health Thermometer, …) and likely to
  miss something useful. Block-list is the cheaper, safer pattern.
- **Don't touch Generic Access / Generic Attribute / Device Information
  in the per-row Services rendering.** Those labels are correct in
  context.
- **Don't change the i18n catalog.** No new user-visible strings
  are introduced.

## Decisions

### Block-list of three UUIDs, not an allow-list

The "what counts as a device kind" question doesn't have a clean
positive definition — Battery / HID / Heart Rate / Audio are all
clearly kinds, but lots of more obscure services (Glucose Monitor,
Continuous Glucose Monitoring, Mesh Proxy, Cycling Power, Object
Transfer Service, Reconnection Configuration, Pulse Oximeter, …)
are also legitimately device-class-meaningful when they actually
appear. Hand-curating an allow-list means deciding case-by-case
and locks out anything not yet seen.

Block-listing the three protocol-utility services covers the
observed bug with the minimal surface area. If a future audit
catches another generic service polluting the row, add it to the
block-list.

### Block-list lives in `ble.py`, not the JSON tables

`bluetooth_member_uuids.json` and `gatt_services.json` are
verbatim mirrors of the SIG-published lists; they don't carry
project-specific filtering. The exclusion set belongs in
`ble.py` next to `service_category()`.

The constant gets a one-line comment citing the audit run that
discovered the issue, so the next person reading the code knows
why these three UUIDs are filtered.

### `category_only=True` is the right place

The two `service_category()` callers already differentiate via
`category_only`:

- BLE list per-row services column → `category_only=False`
- BLE diagnostics Categories aggregator → `category_only=True`

The new filter slots into the existing branch in
`service_category()` — no new caller code, no new function.

### Spec Requirement names the three UUIDs

The new Requirement is precise (lists `1800` / `1801` / `180A`)
rather than abstract ("protocol-utility services"). Future
reviewers can cite the spec to block re-introductions; future
extensions add UUIDs to both the constant and the Requirement
together.

## Risks / Trade-offs

- **Risk**: a contributor removes 0x180A from the block-list
  thinking "but Device Information IS a service users see, why
  hide it from Categories?", re-introducing the bug.
  → **Mitigation**: spec Requirement plus the audit-citation
  comment in the source code make the rationale visible at every
  level a reviewer might look.

- **Trade-off**: the block-list grows by hand. If a generic GATT
  service starts to appear and pollutes the Categories row, the
  fix is one more entry in the constant. That's fine — empirical
  growth keeps the list tight.

- **Risk**: the test fixture might over-specify and break on
  legitimate future changes to the layered resolution order.
  → **Mitigation**: the test asserts only the externally-visible
  return value (`None` for category_only / friendly name for
  default), not the internal layer order.

## Migration Plan

1. Cut `fix/ble-categories-exclude-protocol-services` (already
   done — branch exists pre-OpenSpec scaffolding).
2. Land Phase A: OpenSpec change scaffolding (proposal/design/
   specs/tasks).
3. Land Phase B: code change + test + TESTING.md + CHANGELOG.
4. Run the four CI gates locally; push.
5. Open PR. Wait CI. Merge.
6. Archive: `openspec archive ble-categories-exclude-protocol-services`
   applies the delta into canonical `bluetooth-scanning` spec.

Nothing to roll back — Phase B is one filter + one test.

## Open Questions

None. The block-list scope is intentionally minimal; future audits
can extend it.
