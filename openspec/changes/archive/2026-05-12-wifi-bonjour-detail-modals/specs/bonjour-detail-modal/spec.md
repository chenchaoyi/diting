## ADDED Requirements

### Requirement: Bonjour list rows SHALL be selectable by service-instance FQDN, stable across snapshots
The App SHALL track a single `_bonjour_selected_key: str | None`
keyed by `f"{name}.{service_type}"` (the service-instance
fully-qualified name on the local link). Each snapshot's render
SHALL highlight the row whose key matches the selection. If the
selected service drops out of the snapshot, the selection SHALL
clear to `None` — the cursor MUST NOT silently jump to a different
service.

#### Scenario: Cursor stable through re-sort
- **WHEN** the user selects an `Office HomePod._raop._tcp` instance and another instance is added that sorts above it
- **THEN** the highlight stays on `Office HomePod`, even though its row index changed

#### Scenario: Service goes silent
- **WHEN** the user selects an AirPlay receiver that stops announcing and gets pruned from the snapshot
- **THEN** the next render clears the selection (no ghost cursor)

### Requirement: Keyboard navigation SHALL bind `up` / `down` / `enter` / `i` in the Bonjour view
The App SHALL bind `up`/`down` to move selection (priority=True so
they fire before `VerticalScroll`'s built-in scroll handler) and
`enter`/`i` to open the Bonjour detail modal for the current
selection. All bindings SHALL be no-ops outside the Bonjour view.

#### Scenario: Bonjour view, user presses down
- **WHEN** the user is in Bonjour view and presses ↓
- **THEN** selection moves to the next service row, highlight follows

#### Scenario: First press with no prior selection
- **WHEN** the user has not yet moved the cursor in Bonjour view and presses `i`
- **THEN** the modal opens for the first row in panel order

### Requirement: Mouse click on a Bonjour row SHALL select-and-inspect in one gesture
A click on any data row in the Bonjour panel SHALL set selection to
that row and open the detail modal in the same gesture. Clicks on
header / spacer / empty-state rows SHALL be no-ops. Coordinates SHALL
be translated via Textual's `event.get_content_offset(body)`.

#### Scenario: Click on a service row
- **WHEN** the user clicks on a row showing `Office HomePod  AirPlay  ...`
- **THEN** the row highlight moves there and the detail modal opens for that service

#### Scenario: Click on the section header
- **WHEN** the user clicks on a header / placeholder line
- **THEN** nothing happens (no modal opens, selection unchanged)

### Requirement: The modal SHALL render every `BonjourDevice` field, grouped into sections
The modal layout SHALL be a vertical sequence of sections, in this
order, with sections omitted when their data is absent:

1. **Identity** — instance name (with the `._<service-type>.local.`
   suffix stripped, matching list rendering), service type token,
   service category (i18n-translated when available), vendor
2. **Network** — host (with `.local` suffix shown explicitly),
   port, addresses (full list, IPv4 and IPv6 rendered separately,
   one per line)
3. **TXT records** — every TXT key/value pair from the `txt` dict,
   rendered as a 2-column table. Values longer than 60 characters
   SHALL be folded to `<N-byte payload>` plus the first 32 hex
   characters of the raw value as a one-line preview, so AirPlay
   receivers with 30+ TXT keys don't blow out the modal height.
4. **Activity** — first seen / last seen as "Xs ago"

#### Scenario: Open modal on an AirPlay receiver with 18 TXT keys
- **WHEN** the user inspects a `Living HomePod._raop._tcp` row
- **THEN** every TXT key (`md`, `am`, `vs`, `vn`, `tp`, `pk`, …) renders; the long `pk=` value is folded to `<256-byte payload> 8d4b… (hex)`

#### Scenario: Open modal on a service with no TXT
- **WHEN** the user inspects a row whose `txt` dict is empty
- **THEN** the TXT records section is absent entirely

#### Scenario: Open modal on a service with both IPv4 and IPv6 addresses
- **WHEN** the user inspects a row whose `addresses` tuple contains `192.168.1.42` and `fe80::1c4`
- **THEN** the Network section shows two address rows, IPv4 first

### Requirement: Service-type names SHALL render via i18n service-category lookup
The Identity section's service-category row SHALL come from the same
`service_category()` lookup the list view uses, so a row labelled
"AirPlay Audio Receiver" in the list reads "AirPlay Audio Receiver"
in the modal. When the lookup returns `None`, the row SHALL omit
the category line and show just the raw service type token.

#### Scenario: Known service type
- **WHEN** the user inspects an `_raop._tcp` row
- **THEN** the Identity section shows `service type: _raop._tcp` and `category: AirPlay Audio Receiver`

#### Scenario: Unknown service type
- **WHEN** the user inspects a row with service type `_xyz._tcp` that has no entry in the i18n catalogue
- **THEN** the Identity section shows `service type: _xyz._tcp` and omits the category row

### Requirement: Modal close SHALL be Esc / `i` / `q`, and SHALL NOT mutate selection
The modal SHALL bind `escape`, `i`, and `q` to close. Closing SHALL
NOT clear `_bonjour_selected_key` — the user expects the highlighted
row to remain highlighted. Reopening with `i` without other key
presses SHALL show the same row.

#### Scenario: User opens modal, reads, closes, reopens
- **WHEN** the user presses `i` → reads → Esc → `i`
- **THEN** the second `i` opens the modal for the same service

### Requirement: While the modal is open, `up` / `down` SHALL track selection live
The TUI SHALL advance the underlying Bonjour selection when the user
presses `up` / `down` while `BonjourDetailScreen` is on the screen
stack, AND the modal body MUST re-render to track the new
service-instance's data (Identity / Network / TXT records /
Activity). The user SHALL be able to walk the service list without
closing and reopening the modal each time.

#### Scenario: User opens modal on first service, presses ↓
- **WHEN** the modal is open on an `Office HomePod` instance and the user presses ↓
- **THEN** the underlying selection advances to the next service AND the modal body re-renders with that service's instance name / TXT records / addresses

#### Scenario: ↓ at the bottom of the list
- **WHEN** the modal is open on the last service row and the user presses ↓
- **THEN** the selection stays on that row (clamped), the modal body stays unchanged

### Requirement: The footer SHALL document the close keys in the active locale
The modal SHALL render a footer `Esc / i to close` (English) or its
ZH translation, using the same `t()` lookup as the rest of the TUI.

#### Scenario: ZH locale
- **WHEN** `DITING_LANG=zh` and the user opens the Bonjour detail modal
- **THEN** the footer reads `Esc / i 关闭`
