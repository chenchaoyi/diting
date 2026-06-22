## MODIFIED Requirements

### Requirement: The helper SHALL request Location, Bluetooth, and Notifications permissions in a sequenced flow at install time
When launched as a GUI app (`open <bundle>`), the helper SHALL request the three TCC permissions in the order Location → Bluetooth → Notifications. Each request SHALL fire only after the previous one's authorization callback resolves to a non-`.notDetermined` state (Allow, Don't Allow, restricted, or denied — any settled state). The user SHALL see at most one macOS TCC prompt on screen at any time during install, on top of the persistent helper status window.

The status window SHALL render three lines (one per permission) and update each line's status text as the corresponding callback resolves. The window SHALL auto-close ~4 seconds after the third permission's state has settled.

The status window SHALL be laid out top-aligned: its content SHALL be pinned to the top of the content view with consistent padding and the window SHALL be sized to fit its content, leaving no large empty region. The window SHALL show, from the top down, the bundle's app icon (the diting logo), a bold title, a secondary-color explanatory paragraph, and one status row per permission. Each status row SHALL carry a leading status glyph whose symbol and color reflect that permission's state — pending (not yet reached), in-progress (awaiting the user's decision, rendered in the diting brand color), granted, or denied/restricted — alongside the permission's status text.

If any permission resolves to denied or restricted, the helper SHALL continue to the next permission rather than aborting the flow, and the status line for the denied permission SHALL include a "open System Settings → Privacy & Security → ..." hint.

#### Scenario: User clicks Allow on all three
- **WHEN** the user runs install.sh and clicks Allow on Location, then Allow on Bluetooth, then Allow on Notifications
- **THEN** macOS shows exactly one prompt at a time, never two simultaneously
- **AND** the status window shows each permission's row turn from in-progress to a granted glyph as it lands, in order Location → Bluetooth → Notifications
- **AND** the window auto-closes ~4 seconds after the third grant

#### Scenario: User denies a permission mid-flow
- **WHEN** the user clicks Don't Allow on Bluetooth
- **THEN** the status window shows the Bluetooth row with a denied glyph and a Settings hint
- **AND** the helper still requests Notifications next (does not abort the flow)
- **AND** the window auto-closes after the Notifications outcome resolves

#### Scenario: Window is legibly laid out
- **WHEN** the helper status window appears
- **THEN** its content is top-aligned with the diting app icon at the top and one status row per permission, each with a leading status glyph
- **AND** there is no large empty region above or below the content
