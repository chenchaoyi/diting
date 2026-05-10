// Window.jsx — macOS window chrome
const Window = ({ title = "diting · wifi_main_en", clock = "14:15:19", children }) => (
  <div className="window">
    <div className="window-bar">
      <div className="dots">
        <span className="dot" style={{ background: "#ff5f57" }} />
        <span className="dot" style={{ background: "#febc2e" }} />
        <span className="dot" style={{ background: "#28c840" }} />
      </div>
      <div className="title">{title}</div>
      <div className="clock">{clock}</div>
    </div>
    {children}
  </div>
);

// Panel.jsx — heavy-orange-border container
const Panel = ({ title, scroll = false, children, style }) => (
  <div className={"p" + (scroll ? " scroll" : "")} style={style}>
    <span className="pt">{title}</span>
    {children}
  </div>
);

// SignalBar — 10-cell meter
const SignalBar = ({ rssi }) => {
  // -30 → 10, -90 → 0
  const filled = Math.max(0, Math.min(10, Math.round((rssi + 90) / 6)));
  return (
    <span className="bar">
      {Array.from({ length: 10 }).map((_, i) => (
        <i key={i} className={i < filled ? "" : "off"} />
      ))}
    </span>
  );
};

const ConnectionPanel = () => (
  <Panel title="Connection">
    <div>
      <span className="ssid-bold">1F-bedroom</span>
      <span className="ssid-band">  5G</span>
      <span className="dim">  ·  country CN</span>
    </div>
    <div style={{ marginTop: 6 }}>
      <span className="k">SSID</span>Office-WiFi
    </div>
    <div><span className="k">BSSID</span>aa:bb:cc:11:22:53  <span className="dim">·  Apple, Inc.</span></div>
    <div><span className="k">Channel</span>48  80 MHz  5 GHz</div>
    <div><span className="k">PHY / Sec</span>802.11ax   WPA2 Enterprise</div>
    <div><span className="k">Tx / Max</span>360.0 Mbps  /  867 Mbps max</div>
    <div><span className="k">MCS / NSS</span>7  ·  2 streams</div>
    <div><span className="k">Noise</span>-95 dBm</div>
    <div><span className="k">IP / Router</span>192.168.1.42  →  192.168.1.1</div>
    <div><span className="k">This Mac</span>de:ad:be:ef:00:01</div>
    <div style={{ marginTop: 6 }}>
      <span className="k">Signal</span>
      <span className="ok">-58 dBm</span>
      {"  "}
      <SignalBar rssi={-58} />
    </div>
    <div className="fnote">  * Tx and Max use different CoreWLAN APIs and may diverge.</div>
  </Panel>
);

const DiagnosticsPanel = () => (
  <Panel title="Diagnostics">
    <div>
      <span className="dim">visible</span>{" "}6 BSSIDs / 3 APs
      <span className="dim">  ·  </span><span className="warn">2 open</span>
      <span className="dim">  ·  </span>countries CN
      <span className="dim">  ·  recommend</span>{" "}
      <span className="info">2.4G ch1</span>
      <span className="info">  5G ch36</span>
    </div>
    <div style={{ marginTop: 4 }}>
      <span className="dim">current  </span>
      <span className="ok">good signal -58 dBm</span>
      <span className="dim">  ·  </span>
      <span className="ok">SNR 37 dB</span>
      <span className="dim">  ·  </span>
      <span className="info">roam score 78</span>
    </div>
    <div style={{ marginTop: 4 }}>
      <span className="k">Link</span>
      <span className="ok">gw 1.2 ms</span>{"  "}
      <span className="ok">DNS 11 ms</span>{"  "}
      <span className="ok">loss 0%</span>
    </div>
    <div>
      <span className="k">Env</span>
      <span className="ok">stable</span>
      <span className="dim">   σ 1.8 dB / per-AP σ 2.1 · 2.4 · 1.6</span>
    </div>
  </Panel>
);

const ScanRow = ({ ap, band, ch, w, rssi, sec, current, unknown, open, alt }) => {
  const cls =
    "scan-row" + (current ? " cur" : "") + (unknown ? " unk" : "") + (alt ? " alt" : "");
  const rssiCls = rssi > -60 ? "ok" : rssi > -75 ? "warn" : "alert";
  return (
    <div className={cls}>
      <div className="ap">{ap}</div>
      <div className="info">{band}</div>
      <div>ch{ch}</div>
      <div>{w} MHz</div>
      <div className={rssiCls}>{rssi} dBm</div>
      <div className={open ? "warn" : ""} style={open ? { fontWeight: 700 } : {}}>
        {open ? "OPEN" : sec}
      </div>
      <div>{current ? <span className="info" style={{ fontWeight: 700 }}>★</span> : ""}</div>
      <div className="dim" style={{ fontSize: 12 }}>
        {open ? "(captive likely)" : ""}
      </div>
    </div>
  );
};

const ScanPanel = () => (
  <Panel title="Nearby BSSIDs (6) · scanned 2s ago · sort: signal" scroll>
    <div className="scan-head">
      <div>AP</div><div>band</div><div>ch</div><div>width</div>
      <div>RSSI</div><div>security</div><div></div><div></div>
    </div>
    <div className="cluster-head">1F-bedroom · 2 radios</div>
    <ScanRow ap="1F-bedroom" band="5G" ch={48} w={80} rssi={-58} sec="WPA2 Ent" current />
    <ScanRow ap="1F-bedroom" band="2.4G" ch={6} w={20} rssi={-72} sec="WPA2 Ent" alt />
    <div className="cluster-head">2F-living · 1 radio</div>
    <ScanRow ap="2F-living" band="5G" ch={36} w={80} rssi={-65} sec="WPA2 Ent" />
    <div className="cluster-head">3F-attic · 1 radio</div>
    <ScanRow ap="3F-attic" band="5G" ch={48} w={80} rssi={-70} sec="WPA2 Ent" alt />
    <div className="cluster-head">?96:de:ad · unmapped</div>
    <ScanRow ap="?96:de:ad" band="5G" ch={48} w={20} rssi={-75} sec="—" unknown open />
    <ScanRow ap="?f2:11:22" band="2.4G" ch={6} w={20} rssi={-78} sec="WPA2" unknown alt />
  </Panel>
);

const RoamLog = () => (
  <Panel title="Roam log" scroll>
    <div className="event">
      <span className="ts">14:15:19</span>
      <span className="tag tag-roam">[ROAM]</span>
      inter-AP  1F-bedroom → 2F-living  <span className="info">Δ +14 dB</span>
    </div>
    <div className="event">
      <span className="ts">14:14:02</span>
      <span className="tag tag-stir">[STIR]</span>
      2F-living  <span className="warn">σ 6.4 → 11.8 dB</span>  confidence high
    </div>
    <div className="event">
      <span className="ts">14:11:48</span>
      <span className="tag tag-loss">[LOSS]</span>
      gateway  3/30 echoes  <span className="alert">10%</span>
    </div>
    <div className="event">
      <span className="ts">14:09:11</span>
      <span className="tag tag-link">[LINK]</span>
      WAN reachable  DNS 13 ms
    </div>
    <div className="event">
      <span className="ts">14:02:55</span>
      <span className="tag tag-roam">[ROAM]</span>
      band switch on 1F-bedroom: 2.4G → 5G
    </div>
  </Panel>
);

const BlePanel = () => (
  <Panel title="Nearby BLE devices · 14 advertising · 4 connected" scroll>
    <div className="cluster-head">Connected peripherals</div>
    <div className="event"><span className="info" style={{ fontWeight: 700, width: 220 }}>AirPods Pro</span><span className="dim">Apple, Inc.   —    audio</span></div>
    <div className="event"><span className="info" style={{ fontWeight: 700, width: 220 }}>Magic Keyboard</span><span className="dim">Apple, Inc.   —    HID</span></div>
    <div className="event"><span className="info" style={{ fontWeight: 700, width: 220 }}>Apple Watch S9</span><span className="dim">Apple, Inc.   —    Continuity</span></div>
    <div className="cluster-head">Advertising</div>
    <div className="event"><span style={{ width: 220 }} className="info">AirTag</span><span className="ok">-52 dBm</span><span className="dim">   Find My  ·  iBeacon</span></div>
    <div className="event"><span style={{ width: 220 }} className="info">iPhone (Nearby Info)</span><span className="ok">-58 dBm</span><span className="dim">   Apple Continuity</span></div>
    <div className="event"><span style={{ width: 220 }}>HomePod mini</span><span className="warn">-71 dBm</span><span className="dim">   AirPlay</span></div>
    <div className="event"><span style={{ width: 220 }}>Eddystone-URL</span><span className="warn">-74 dBm</span><span className="dim">   bit.ly/coffee</span></div>
    <div className="event"><span style={{ width: 220 }} className="dim">(anonymous)</span><span className="alert">-83 dBm</span><span className="dim">   no vendor · no name  ·  (merged 2)</span></div>
  </Panel>
);

const Footer = ({ active = "wifi" }) => (
  <div className="footer">
    <span><span className="key">q</span> quit</span>
    <span><span className="key">p</span> pause</span>
    <span><span className="key">r</span> rescan</span>
    <span><span className="key">s</span> sort</span>
    <span><span className="key">n</span> {active === "ble" ? "Wi-Fi" : "BLE"}</span>
    <span><span className="key">c</span> re-roam</span>
    <span><span className="key">m</span> events</span>
    <span><span className="key">h</span> help</span>
    <span><span className="key">b</span> basics</span>
  </div>
);

const EventsModal = ({ onClose }) => (
  <div className="modal-backdrop" onClick={onClose}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <span className="modal-title">Events (12)</span>
      <div style={{ marginBottom: 10 }}>
        <h4 style={{ color: "var(--warn-bold)", margin: "0 0 4px" }}>Per-AP σ baseline</h4>
        <div className="dim">1F-bedroom 2.1 dB  ·  2F-living 2.4 dB  ·  3F-attic 1.6 dB</div>
        <h4 style={{ color: "var(--warn-bold)", margin: "12px 0 4px" }}>Last hour σ sparkline</h4>
        <div style={{ fontSize: 18, color: "var(--fg2)" }}>▁▂▂▃▃▂▁▂▄▆▅▃▂▂▁▂▃▄▃▂▁▁▁▂</div>
      </div>
      <div style={{ borderTop: "1px solid rgba(255,255,255,.06)", paddingTop: 10 }}>
        <div className="event"><span className="ts">14:15:19</span><span className="tag tag-roam">[ROAM]</span>inter-AP  1F-bedroom → 2F-living  <span className="info">Δ +14 dB</span></div>
        <div className="event"><span className="ts">14:14:02</span><span className="tag tag-stir">[STIR]</span>2F-living  <span className="warn">σ 6.4 → 11.8 dB</span></div>
        <div className="event"><span className="ts">14:11:48</span><span className="tag tag-loss">[LOSS]</span>gateway  <span className="alert">10%</span></div>
        <div className="event"><span className="ts">14:09:11</span><span className="tag tag-link">[LINK]</span>WAN reachable  DNS 13 ms</div>
        <div className="event"><span className="ts">14:02:55</span><span className="tag tag-roam">[ROAM]</span>band switch on 1F-bedroom: 2.4G → 5G</div>
        <div className="event"><span className="ts">13:48:11</span><span className="tag tag-stir">[STIR]</span>3F-attic  σ 1.6 → 4.9 dB</div>
        <div className="event"><span className="ts">13:30:02</span><span className="tag tag-loss">[LOSS]</span>DNS  <span className="warn">8%</span></div>
        <div className="event"><span className="ts">13:11:00</span><span className="tag tag-link">[LINK]</span>WAN unreachable  DNS 1.2 ms</div>
      </div>
      <div className="dim" style={{ marginTop: 10, fontSize: 12 }}>m close · ↑/↓ scroll · t cycle filter</div>
    </div>
  </div>
);

const App = () => {
  const [view, setView] = React.useState("wifi");
  const [modal, setModal] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "n") setView((v) => (v === "wifi" ? "ble" : "wifi"));
      if (e.key === "m") setModal((m) => !m);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <Window title={`diting · ${view === "wifi" ? "wifi_main_en" : "ble_normal"}`}>
      <div className="nav">
        <button className={view === "wifi" ? "active" : ""} onClick={() => setView("wifi")}>view: wifi</button>
        <button className={view === "ble" ? "active" : ""} onClick={() => setView("ble")}>view: ble</button>
        <button onClick={() => setModal(true)} style={{ marginLeft: "auto" }}>open events (m)</button>
      </div>
      <div className="tui" style={{ position: "relative" }}>
        {view === "wifi" ? (
          <>
            <ConnectionPanel />
            <DiagnosticsPanel />
            <ScanPanel />
            <RoamLog />
          </>
        ) : (
          <>
            <ConnectionPanel />
            <DiagnosticsPanel />
            <BlePanel />
            <RoamLog />
          </>
        )}
        {modal && <EventsModal onClose={() => setModal(false)} />}
      </div>
      <Footer active={view} />
    </Window>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
