"""Headless capture engine.

`CaptureEngine` assembles and drives diting's sensors — Wi-Fi, latency,
RF/environment, BLE, LAN, mDNS/Bonjour — below the UI, emitting the same
canonical event-log JSONL the TUI writes via `EventLogger`. It exists so a
headless `diting stream` (and, later, managed capture sessions) sees
everything the dashboard sees instead of Wi-Fi only.

Every poller self-diffs internally and exposes `drain_transitions()`; the
engine's consumers are thin — iterate `events()`, drain, route each
transition to the matching `EventLogger.emit_*`. There is deliberately no
Textual / widget coupling here (the engine is the headless half of what
`DitingApp` does in `on_mount`).
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone

from .environment import EnvironmentMonitor, load_calibration
from .event_log import EventLogger, build_monitors_manifest
from .events import (
    BLEDeviceLeftEvent,
    BLEDeviceSeenEvent,
    BonjourServiceLeftEvent,
    BonjourServiceSeenEvent,
    LANHostDHCPRotationEvent,
    LANHostLeftEvent,
    LANHostSeenEvent,
    LatencySpikeEvent,
    LossBurstEvent,
    NetworkChangeEvent,
)
from .i18n import t
from .latency import LatencyPoller, detect_latency_spike, detect_loss_burst
from .network import lookup_ap_vendor
from .poller import ConnectionUpdate, RoamEvent, ScanUpdate, WiFiPoller

# The full sensor vocabulary `--sensors` accepts (plus `all`). `wifi` is
# implied whenever `latency` or `rf` is requested (both derive from the
# Wi-Fi stream).
ALL_SENSORS = ("wifi", "latency", "rf", "ble", "lan", "mdns")


class CaptureEngine:
    """Drive the selected sensors and emit canonical JSONL via `logger`.

    Construct with the resolved sensor set and the scene-derived gate /
    probe values, then `await run(duration_s=...)`. `run` returns when the
    bounded window elapses; an unbounded run blocks until the task is
    cancelled (Ctrl+C / SIGTERM). Teardown (stop pollers, flush stores,
    close the logger) always runs.
    """

    def __init__(
        self,
        backend,
        inv,
        *,
        logger: EventLogger,
        sensors,
        scene_source: str = "default",
        ble_helper_path: str | None = None,
        ble_presence_gate_s: float = 5.0,
        lan_active_probe: bool = False,
        lan_upnp_fetch: bool = True,
        scan_interval: float = 7.0,
        gateway_override: str | None = None,
        wan_override: str | None = None,
        notify: bool = False,
    ) -> None:
        self._backend = backend
        self._inv = inv
        self._logger = logger
        self._sensors = set(sensors)
        self._scene_source = scene_source
        self._ble_helper_path = ble_helper_path or None
        self._ble_presence_gate_s = ble_presence_gate_s
        self._lan_active_probe = lan_active_probe
        self._lan_upnp_fetch = lan_upnp_fetch
        self._scan_interval = scan_interval
        self._gateway_override = gateway_override
        self._wan_override = wan_override
        self._notify_enabled = notify

        self._active = self._resolve_active()
        self._rf_active = self._active["rf"]
        self._mdns_active = self._active["mdns"]

        self._latest_connection = None
        self._monitor: EnvironmentMonitor | None = None
        self._bonjour = None
        self._lan = None
        self._familiarity = None
        self._companion_sink = None
        self._companion_runtime = None
        self._flush_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._last_event_at: dict[tuple[str, str], float] = {}

        # Watchdog (notify) state — mirrors `_run_monitor`'s prior wiring.
        if notify:
            from ._watchdog import SilenceClock, WatchdogConfig
            self._watchdog_cfg = WatchdogConfig.from_env()
            self._silence_clock = SilenceClock(self._watchdog_cfg.silence_window_s)
        else:
            self._watchdog_cfg = None
            self._silence_clock = None

    # ---------- sensor resolution ----------

    def _resolve_active(self) -> dict[str, bool]:
        s = self._sensors
        wifi = ("wifi" in s) or ("latency" in s) or ("rf" in s)
        return {
            "wifi": wifi,
            "latency": "latency" in s,
            "rf": "rf" in s,
            # BLE needs a helper bundle with the ble-scan subcommand. The
            # caller resolves the path; absent means BLE can't start.
            "ble": ("ble" in s) and bool(self._ble_helper_path),
            "lan": "lan" in s,
            "mdns": "mdns" in s,
        }

    def active_sensors(self) -> dict[str, bool]:
        """The sensors that will actually run (post availability checks)."""
        return dict(self._active)

    def _note(self, message: str) -> None:
        # Status / degradation notes go to stderr so stdout stays pure JSONL.
        print(f"diting: {message}", file=sys.stderr)

    # ---------- lifecycle ----------

    async def run(self, duration_s: float | None = None) -> None:
        self._setup()
        self._spawn_consumers()
        try:
            if duration_s is not None:
                await asyncio.sleep(duration_s)
            else:
                # Run until cancelled. Consumers self-isolate runtime errors,
                # so this gather only returns on cancellation.
                if self._tasks:
                    await asyncio.gather(*self._tasks)
                else:
                    # No sensors selected at all — nothing to do; idle until
                    # cancelled rather than exiting immediately.
                    await asyncio.Event().wait()
        finally:
            await self._teardown()

    def _setup(self) -> None:
        from . import scene as _scene_mod
        from . import familiarity as _familiarity

        if self._rf_active:
            self._monitor = EnvironmentMonitor(
                inventory=self._inv, calibration=load_calibration(),
            )

        # Companion forwarding (opt-in via `diting companion pair`).
        try:
            from .companion import runtime as _companion_runtime
            self._companion_sink = _companion_runtime.build_sink()
            self._companion_runtime = _companion_runtime
        except Exception:
            self._companion_sink = None
        if self._companion_sink is not None:
            self._logger.set_observer(self._companion_sink.offer)

        # Familiarity / baseline store — classifies seen events.
        try:
            self._familiarity = _familiarity.FamiliarityStore(
                _familiarity.default_store_path(),
            )
            self._logger.set_familiarity_store(self._familiarity)
        except Exception:
            self._familiarity = None

        # `ble` requested but unavailable → tell the user once.
        if ("ble" in self._sensors) and not self._active["ble"]:
            self._note(t(
                "BLE sensor requested but no helper with ble-scan is "
                "available; continuing without BLE",
            ))

        # Synchronously fetch the connection once so session_meta carries
        # the at-launch SSID + gateway rather than null.
        try:
            startup_conn = self._backend.get_connection()
        except Exception:
            startup_conn = None
        try:
            perm = self._backend.permission_state()
        except Exception:
            perm = None
        if startup_conn is not None:
            self._latest_connection = startup_conn

        a = self._active
        self._logger.emit_session_meta(
            scene=_scene_mod.get_scene(),
            scene_source=self._scene_source,
            ssid=startup_conn.ssid if startup_conn else None,
            gateway_ip=startup_conn.router_ip if startup_conn else None,
            # The manifest reflects what the engine ACTUALLY wired — no
            # more hard-coded ble=false / lan=false.
            monitors=build_monitors_manifest(
                wifi=a["wifi"],
                scan_interval_s=self._scan_interval if a["wifi"] else None,
                ble=a["ble"],
                ble_gate_s=self._ble_presence_gate_s if a["ble"] else None,
                lan=a["lan"],
                latency=a["latency"],
                rf_stir=a["rf"],
            ),
            permissions={"location": perm} if perm is not None else None,
        )

        # Bonjour MUST be constructed before LAN and shared into it, so LAN
        # keeps its Bonjour-name enrichment (the TUI invariant).
        if a["mdns"] or a["lan"]:
            try:
                from .mdns import BonjourPoller
                self._bonjour = BonjourPoller()
            except Exception as exc:  # noqa: BLE001 — degrade, don't crash
                self._note(t(
                    "mDNS/Bonjour unavailable: {err}", err=str(exc),
                ))
                self._bonjour = None

    def _spawn_consumers(self) -> None:
        a = self._active
        if a["wifi"]:
            self._tasks.append(asyncio.create_task(
                self._wifi_consumer(), name="cap-wifi",
            ))
        if a["latency"]:
            self._tasks.append(asyncio.create_task(
                self._latency_consumer(), name="cap-latency",
            ))
        if a["ble"]:
            self._tasks.append(asyncio.create_task(
                self._ble_consumer(), name="cap-ble",
            ))
        # Drive Bonjour whenever it was constructed (LAN enrichment needs its
        # events() pumped even when mDNS events aren't being emitted).
        if self._bonjour is not None:
            self._tasks.append(asyncio.create_task(
                self._bonjour_consumer(), name="cap-mdns",
            ))
        if a["lan"]:
            self._tasks.append(asyncio.create_task(
                self._lan_consumer(), name="cap-lan",
            ))
        if self._companion_sink is not None and self._companion_runtime is not None:
            self._flush_task = asyncio.create_task(
                self._companion_runtime.flush_loop(self._companion_sink),
                name="cap-companion-flush",
            )

    async def _teardown(self) -> None:
        # Cancel every consumer + the flush task, then best-effort await so
        # their generators' finally blocks run (terminating helper
        # subprocesses). The flushes below are synchronous, so even if an
        # await is itself cancelled the logger still closes.
        for task in self._tasks:
            task.cancel()
        if self._flush_task is not None:
            self._flush_task.cancel()
        for task in [*self._tasks, self._flush_task]:
            if task is None:
                continue
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for poller in (self._bonjour, self._lan):
            if poller is not None:
                try:
                    poller.stop()
                except Exception:  # noqa: BLE001
                    pass
        if self._familiarity is not None:
            try:
                self._familiarity.flush()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._logger.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- notify / throttle helpers ----------

    async def _notify(self, payload: dict, target: str) -> None:
        if not self._notify_enabled:
            return
        from ._watchdog import maybe_notify
        await maybe_notify(
            payload, target=target,
            clock=self._silence_clock, config=self._watchdog_cfg,
        )

    def _should_fire(self, kind: str, target: str, cooldown_s: float = 30.0) -> bool:
        now = time.monotonic()
        last = self._last_event_at.get((kind, target))
        if last is not None and (now - last) < cooldown_s:
            return False
        self._last_event_at[(kind, target)] = now
        return True

    def _fire_network_change(
        self, *, previous_router_ip: str | None, new_router_ip: str | None,
    ) -> None:
        new_ssid = self._latest_connection.ssid if self._latest_connection else None
        new_bssid = self._latest_connection.bssid if self._latest_connection else None
        ev = NetworkChangeEvent(
            timestamp=datetime.now().astimezone(),
            previous_router_ip=previous_router_ip,
            new_router_ip=new_router_ip,
            previous_ssid=None,
            new_ssid=new_ssid,
            previous_bssid=None,
            new_bssid=new_bssid,
        )
        self._logger.emit_network_change(ev)
        # Reset event-throttle bookkeeping so the first incident on the new
        # network fires immediately rather than being suppressed by a
        # cooldown left over from the old network.
        self._last_event_at.clear()

    # ---------- consumers ----------

    async def _wifi_consumer(self) -> None:
        poller = WiFiPoller(self._backend, scan_interval=self._scan_interval)
        sampling_channel: dict[str, int | None] = {"value": None}
        try:
            async for event in poller.events():
                now = datetime.now(timezone.utc)
                if isinstance(event, ConnectionUpdate):
                    conn = event.connection
                    if conn is not None:
                        self._latest_connection = conn
                    self._logger.emit_connection_update(
                        conn, now=now,
                        vendor=lookup_ap_vendor(conn.bssid if conn else None),
                    )
                    sampling_channel["value"] = conn.channel if conn else None
                    self._logger.emit_link_sample(conn, now=now)
                    if conn is None:
                        continue
                    if (
                        self._monitor is not None
                        and conn.bssid is not None
                        and conn.rssi_dbm is not None
                    ):
                        self._monitor.ingest(
                            conn.bssid, conn.rssi_dbm, now, ssid=conn.ssid,
                        )
                        for stir in self._monitor.fire_events(now):
                            self._logger.emit_rf_stir(stir)
                            await self._notify(
                                {"type": "rf_stir", "confidence": stir.confidence,
                                 "location": stir.location},
                                target=stir.location,
                            )
                elif isinstance(event, ScanUpdate):
                    if self._monitor is not None:
                        for r in event.results:
                            if r.bssid is not None and r.rssi_dbm is not None:
                                self._monitor.ingest(
                                    r.bssid, r.rssi_dbm, now, ssid=r.ssid,
                                )
                    ch = sampling_channel["value"]
                    self._logger.emit_scan_summary(
                        neighbor_count=len(event.results),
                        co_channel_count=(
                            sum(1 for r in event.results if r.channel == ch)
                            if ch is not None else None
                        ),
                        current_channel=ch,
                        now=now,
                    )
                    if self._monitor is not None:
                        for stir in self._monitor.fire_events(now):
                            self._logger.emit_rf_stir(stir)
                            await self._notify(
                                {"type": "rf_stir", "confidence": stir.confidence,
                                 "location": stir.location},
                                target=stir.location,
                            )
                elif isinstance(event, RoamEvent):
                    kind = (
                        "band_switch"
                        if self._inv.is_same_ap(event.previous_bssid, event.new_bssid)
                        else "inter_ap"
                    )
                    self._logger.emit_roam(
                        event, kind=kind,
                        ssid=self._latest_connection.ssid if self._latest_connection else None,
                        previous_vendor=lookup_ap_vendor(event.previous_bssid),
                        new_vendor=lookup_ap_vendor(event.new_bssid),
                    )
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:  # noqa: BLE001 — isolate a poller hiccup
            pass

    async def _latency_consumer(self) -> None:
        current_gw: str | None = None
        while True:
            # Wait for a known gateway (override wins).
            new_gw: str | None = self._gateway_override
            if new_gw is None:
                for _ in range(60):
                    c = self._latest_connection
                    if c is not None and c.router_ip:
                        new_gw = c.router_ip
                        break
                    await asyncio.sleep(0.5)
            if new_gw is None:
                await asyncio.sleep(5.0)
                continue

            # First bind (None → gw) is silent; a later gw_a → gw_b shift
            # emits a NetworkChangeEvent as a segmentation marker.
            if current_gw is not None and current_gw != new_gw:
                self._fire_network_change(
                    previous_router_ip=current_gw, new_router_ip=new_gw,
                )
            current_gw = new_gw

            poller = LatencyPoller(gateway_ip=new_gw, wan_ip=self._wan_override)
            try:
                async for sample in poller.events():
                    # Rebuild on gateway change (unless pinned by override).
                    if self._gateway_override is None:
                        live = self._latest_connection
                        live_gw = live.router_ip if live is not None else None
                        if live_gw and live_gw != current_gw:
                            poller.stop()
                            break
                    history = list(poller._history.get(sample.target, ()))
                    if not history:
                        continue
                    spike = detect_latency_spike(history)
                    if spike is not None and sample is spike and self._should_fire(
                        "latency_spike", sample.target,
                    ):
                        agg = poller.aggregate(sample.target)
                        rtt_ms = round(sample.rtt_ms or 0.0, 1)
                        self._logger.emit_latency_spike(LatencySpikeEvent(
                            timestamp=sample.ts,
                            target=sample.target,
                            target_ip=sample.target_ip,
                            rtt_ms=rtt_ms,
                            loss_pct=round(agg.loss_pct or 0.0, 1),
                        ))
                        await self._notify(
                            {"type": "latency_spike", "target": sample.target,
                             "rtt_ms": rtt_ms},
                            target=sample.target,
                        )
                    if sample.lost and detect_loss_burst(history) and self._should_fire(
                        "loss_burst", sample.target,
                    ):
                        agg = poller.aggregate(sample.target)
                        loss_pct = round(agg.loss_pct or 0.0, 1)
                        self._logger.emit_loss_burst(LossBurstEvent(
                            timestamp=sample.ts,
                            target=sample.target,
                            target_ip=sample.target_ip,
                            loss_pct=loss_pct,
                            lost_in_window=sum(1 for s in history[-5:] if s.lost),
                        ))
                        await self._notify(
                            {"type": "loss_burst", "target": sample.target,
                             "loss_pct": loss_pct},
                            target=sample.target,
                        )
            except (asyncio.CancelledError, GeneratorExit):
                poller.stop()
                raise
            except Exception:  # noqa: BLE001
                poller.stop()
                await asyncio.sleep(1.0)

    async def _ble_consumer(self) -> None:
        from .ble import BLEPoller
        poller = BLEPoller(
            self._ble_helper_path, presence_gate_s=self._ble_presence_gate_s,
        )
        try:
            async for _event in poller.events():
                for t_ev in poller.drain_transitions():
                    if isinstance(t_ev, BLEDeviceSeenEvent):
                        self._logger.emit_ble_device_seen(t_ev)
                    elif isinstance(t_ev, BLEDeviceLeftEvent):
                        self._logger.emit_ble_device_left(t_ev)
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:  # noqa: BLE001
            pass

    async def _bonjour_consumer(self) -> None:
        poller = self._bonjour
        if poller is None:
            return
        try:
            async for _snap in poller.events():
                for t_ev in poller.drain_transitions():
                    if not self._mdns_active:
                        continue  # driven only for LAN enrichment
                    if isinstance(t_ev, BonjourServiceSeenEvent):
                        self._logger.emit_bonjour_service_seen(t_ev)
                    elif isinstance(t_ev, BonjourServiceLeftEvent):
                        self._logger.emit_bonjour_service_left(t_ev)
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:  # noqa: BLE001
            pass

    async def _lan_consumer(self) -> None:
        from .lan import LANInventoryPoller
        poller = LANInventoryPoller(
            connection_provider=lambda: self._latest_connection,
            bonjour_poller=self._bonjour,
            active_probe_enabled=self._lan_active_probe,
            upnp_fetch_enabled=self._lan_upnp_fetch,
        )
        self._lan = poller
        try:
            async for _update in poller.events():
                for t_ev in poller.drain_transitions():
                    if isinstance(t_ev, LANHostSeenEvent):
                        self._logger.emit_lan_host_seen(t_ev)
                    elif isinstance(t_ev, LANHostLeftEvent):
                        self._logger.emit_lan_host_left(t_ev)
                    elif isinstance(t_ev, LANHostDHCPRotationEvent):
                        self._logger.emit_lan_host_dhcp_rotation(t_ev)
        except (asyncio.CancelledError, GeneratorExit):
            poller.stop()
            raise
        except Exception:  # noqa: BLE001
            poller.stop()
