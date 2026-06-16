## MODIFIED Requirements

### Requirement: A cooldown SHALL prevent the same AP from spamming events
After a stir event fires for a given AP, the detector SHALL suppress
further events from that AP for `DEFAULT_COOLDOWN_S` (8 s) AND
SHALL require σ to drop below `DEFAULT_REARM_DB` (1.5 dB) before
re-arming. Re-arming SHALL require **positive, sustained evidence** that the
disturbance ended: a *computable* σ (the spike window has enough samples)
observed below `DEFAULT_REARM_DB` continuously for at least
`DEFAULT_REARM_DEBOUNCE_S`. A tick whose σ is uncomputable (too few samples in
the spike window — the common case for a neighbour AP sampled only at scan
cadence) SHALL NOT re-arm and SHALL NOT count toward the debounce; a single
below-floor reading that is not sustained SHALL NOT re-arm. This combination
prevents one large stir from re-firing on each subsequent tick while the spike
is still elevated OR while σ is merely unmeasured, so a sustained episode
yields exactly one event.

#### Scenario: Sustained 30-second stir
- **WHEN** σ jumps to 12 dB and stays there for 30 s
- **THEN** exactly ONE `RFStirEvent` fires; the cooldown + rearm guards prevent duplicates

#### Scenario: Undersampled neighbour AP whose σ is intermittently uncomputable
- **WHEN** a co-located neighbour AP is in a sustained stir but its 5 s spike window repeatedly drops below 3 samples (scan-cadence sampling), so `current σ` alternates between a high value and "uncomputable"
- **THEN** the uncomputable ticks do NOT re-arm the AP, so it does NOT re-fire every tick — exactly ONE event covers the ongoing episode

#### Scenario: Two separate disturbances 20 s apart
- **WHEN** a stir at t=0 returns to a sustained σ < 1.5 (computable, held for the debounce window) by t=10, then a fresh stir at t=20
- **THEN** two separate events fire (rearm satisfied between them)

#### Scenario: A single fluke-low σ reading mid-episode does not re-arm
- **WHEN** an ongoing stir momentarily reads one σ below `DEFAULT_REARM_DB` but immediately returns above the floor before `DEFAULT_REARM_DEBOUNCE_S` elapses
- **THEN** the AP stays disarmed and no duplicate event fires
