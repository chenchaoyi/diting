## ADDED Requirements

### Requirement: BLE Categories diagnostic SHALL exclude protocol-utility GATT services
The aggregate Categories diagnostic row in the BLE view SHALL NOT count the three generic protocol-utility GATT services as device kinds: `1800` (Generic Access), `1801` (Generic Attribute), and `180A` (Device Information). These services are advertised by virtually every BLE peripheral that supports bonding, so including them in the Categories breakdown inflates a top-of-list count that reads like a device-class label but contains no information about what kinds of devices are actually around.

The per-row "Services" column SHALL continue to render these names when a device's UUID list includes them, because in a single device's row they ARE useful detail.

The exclusion is implemented via the `category_only=True` flag on `service_category(uuid, *, category_only)` in `src/diting/ble.py`. Future protocol-utility UUIDs that pollute the Categories row in the same way SHALL be added to the same exclusion set rather than introducing a new filter layer.

#### Scenario: Device Information service excluded from Categories breakdown
- **WHEN** the BLE diagnostic strip computes its Categories row over a snapshot containing 20 devices that advertise `180A`
- **THEN** the Categories row SHALL NOT include `Device Information 20` as a category
- **AND** if those 20 devices also advertise other categorisable services (e.g. `iPhone`, `HID`, `Heart Rate`), those categories SHALL still be counted

#### Scenario: Device Information service still rendered in per-row Services column
- **WHEN** a single BLE row's services column resolves `180A` (without `category_only=True`)
- **THEN** the column SHALL display `Device Information`
- **AND** the BLE detail modal SHALL show `Device Information` in the Services section
