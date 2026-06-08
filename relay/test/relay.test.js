// Relay integration tests — run inside the Workers runtime with a local
// D1 (`npm ci && npm test`). NOTE: authored without a reachable npm
// registry, so these were not executed in-repo; treat a first run as
// part of relay bring-up.

import { env, createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index.js";
import { tokenHash } from "../src/auth.js";

const CH = "chan-1";
const TOKEN = "test-bearer-token";
const AUTH = { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" };

const SCHEMA = [
  "DROP TABLE IF EXISTS envelopes",
  "DROP TABLE IF EXISTS channels",
  "DROP TABLE IF EXISTS presence",
  "CREATE TABLE channels (channel TEXT PRIMARY KEY, token_hash TEXT NOT NULL, apns_token TEXT, apns_sandbox INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)",
  "CREATE TABLE envelopes (channel TEXT NOT NULL, seq INTEGER NOT NULL, ts TEXT NOT NULL, body TEXT NOT NULL, expiry INTEGER NOT NULL, PRIMARY KEY (channel, seq))",
  "CREATE TABLE presence (channel TEXT NOT NULL, puller TEXT NOT NULL, last_seen INTEGER NOT NULL, PRIMARY KEY (channel, puller))",
];

beforeEach(async () => {
  for (const stmt of SCHEMA) await env.DB.prepare(stmt).run();
});

function envelope(seq) {
  return { v: 1, ch: CH, seq, ts: "2026-05-20T12:00:00+08:00", n: "bm9uY2U", ct: "Y2lwaGVy" };
}

async function call(method, path, { body, headers } = {}) {
  const ctx = createExecutionContext();
  const req = new Request(`https://relay.test${path}`, {
    method,
    headers: headers || {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const res = await worker.fetch(req, env, ctx);
  await waitOnExecutionContext(ctx);
  return res;
}

const store = (seq) => call("POST", `/v1/channel/${CH}`, { body: envelope(seq), headers: AUTH });
const pull = (since) =>
  call("GET", `/v1/channel/${CH}${since != null ? `?since=${since}` : ""}`, { headers: AUTH });
// A pull from a specific source IP — the relay keys presence on the
// connection, so different IPs are distinct pullers, repeats are one.
const pullFrom = (ip) =>
  call("GET", `/v1/channel/${CH}`, { headers: { ...AUTH, "cf-connecting-ip": ip } });
const presence = (headers) =>
  call("GET", `/v1/channel/${CH}/presence`, { headers: headers || AUTH });

describe("store and forward", () => {
  it("stores then forwards in order", async () => {
    expect((await store(1)).status).toBe(200);
    expect((await store(2)).status).toBe(200);
    const res = await pull(0);
    expect(res.status).toBe(200);
    const { envelopes, cursor } = await res.json();
    expect(envelopes.map((e) => e.seq)).toEqual([1, 2]);
    expect(cursor).toBe(2);
  });

  it("pulls only items after the cursor", async () => {
    await store(1);
    await store(2);
    await store(3);
    const { envelopes, cursor } = await (await pull(1)).json();
    expect(envelopes.map((e) => e.seq)).toEqual([2, 3]);
    expect(cursor).toBe(3);
  });

  it("strips the cleartext push sibling before storing the envelope", async () => {
    const res = await call("POST", `/v1/channel/${CH}`, {
      body: { ...envelope(1), push: { body: "BLE nearby: 客厅电视", category: "ble" } },
      headers: AUTH,
    });
    expect(res.status).toBe(200);
    const { envelopes } = await (await pull(0)).json();
    expect(envelopes).toHaveLength(1);
    expect(envelopes[0]).toEqual(envelope(1)); // push not persisted
    expect(envelopes[0].push).toBeUndefined();
  });

  it("is idempotent for a retried seq", async () => {
    await store(1);
    await store(1);
    const { envelopes } = await (await pull(0)).json();
    expect(envelopes.map((e) => e.seq)).toEqual([1]);
  });

  it("excludes expired envelopes", async () => {
    await store(1); // binds the channel via TOFU
    await env.DB.prepare(
      "INSERT INTO envelopes (channel, seq, ts, body, expiry) VALUES (?, ?, ?, ?, ?)",
    )
      .bind(CH, 2, "2026-05-20T12:00:02+08:00", JSON.stringify(envelope(2)), 1)
      .run();
    const { envelopes } = await (await pull(0)).json();
    expect(envelopes.map((e) => e.seq)).toEqual([1]); // seq 2 expired
  });
});

describe("auth", () => {
  it("rejects a wrong bearer with 403", async () => {
    await store(1); // binds channel to TOKEN's hash
    const res = await call("GET", `/v1/channel/${CH}`, {
      headers: { authorization: "Bearer wrong-token" },
    });
    expect(res.status).toBe(403);
  });

  it("rejects a missing bearer with 401", async () => {
    const res = await call("POST", `/v1/channel/${CH}`, { body: envelope(1) });
    expect(res.status).toBe(401);
  });

  it("404s a pull on an unknown channel", async () => {
    const res = await call("GET", `/v1/channel/never-paired`, { headers: AUTH });
    expect(res.status).toBe(404);
  });

  it("binds token_hash on first contact (TOFU)", async () => {
    await store(1);
    const row = await env.DB.prepare("SELECT token_hash FROM channels WHERE channel=?")
      .bind(CH)
      .first();
    expect(row.token_hash).toBe(await tokenHash(TOKEN));
  });
});

describe("validation", () => {
  it("rejects an unsupported version", async () => {
    const res = await call("POST", `/v1/channel/${CH}`, {
      body: { ...envelope(1), v: 2 },
      headers: AUTH,
    });
    expect(res.status).toBe(400);
  });

  it("rejects a bad seq", async () => {
    const res = await call("POST", `/v1/channel/${CH}`, {
      body: { ...envelope(0) },
      headers: AUTH,
    });
    expect(res.status).toBe(400);
  });

  it("rejects a channel/path mismatch", async () => {
    const res = await call("POST", `/v1/channel/${CH}`, {
      body: { ...envelope(1), ch: "other" },
      headers: AUTH,
    });
    expect(res.status).toBe(400);
  });
});

describe("apns registration + unpair", () => {
  it("stores an apns token", async () => {
    expect(
      (await call("POST", `/v1/channel/${CH}/apns`, {
        body: { token: "device-token-abc", sandbox: true },
        headers: AUTH,
      })).status,
    ).toBe(200);
    const row = await env.DB.prepare(
      "SELECT apns_token, apns_sandbox FROM channels WHERE channel=?",
    )
      .bind(CH)
      .first();
    expect(row.apns_token).toBe("device-token-abc");
    expect(row.apns_sandbox).toBe(1);
  });

  it("unpair deletes the channel and its envelopes", async () => {
    await store(1);
    expect((await call("DELETE", `/v1/channel/${CH}`, { headers: AUTH })).status).toBe(200);
    const row = await env.DB.prepare("SELECT channel FROM channels WHERE channel=?")
      .bind(CH)
      .first();
    expect(row).toBeNull();
  });
});

describe("channel presence (connected count)", () => {
  it("a pull registers presence; the desktop reads active >= 1", async () => {
    await store(1); // desktop POST binds the channel (TOFU) before phones pull
    await pull(0);
    const res = await presence();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.active).toBe(1);
    expect(body.ttl_s).toBeGreaterThanOrEqual(60);
    expect(typeof body.as_of).toBe("string");
    // Count-only: no identity leaks into the response.
    expect(body).not.toHaveProperty("pullers");
    expect(JSON.stringify(body)).not.toContain("cf-connecting-ip");
  });

  it("distinct connections count separately; repeats from one do not", async () => {
    await store(1); // bind the channel first
    await pullFrom("1.1.1.1");
    await pullFrom("1.1.1.1"); // same puller — still one
    await pullFrom("2.2.2.2"); // different puller — two
    const body = await (await presence()).json();
    expect(body.active).toBe(2);
  });

  it("presence decays after the TTL window", async () => {
    await store(1); // bind the channel first
    await pull(0);
    expect((await (await presence()).json()).active).toBe(1);
    // Age the row past the 90s TTL.
    await env.DB.prepare("UPDATE presence SET last_seen=? WHERE channel=?")
      .bind(Math.floor(Date.now() / 1000) - 1000, CH)
      .run();
    expect((await (await presence()).json()).active).toBe(0);
  });

  it("polling presence does not itself register a puller", async () => {
    // The channel must exist first (presence is a read path → 404 otherwise).
    await store(1);
    await presence();
    await presence();
    expect((await (await presence()).json()).active).toBe(0);
  });

  it("presence requires the channel token", async () => {
    await store(1);
    const res = await presence({ "content-type": "application/json" }); // no bearer
    expect(res.status).toBe(401);
    const bad = await presence({ authorization: "Bearer wrong", "content-type": "application/json" });
    expect(bad.status).toBe(403);
  });

  it("unpair clears presence rows", async () => {
    await store(1); // bind the channel first
    await pull(0);
    await call("DELETE", `/v1/channel/${CH}`, { headers: AUTH });
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM presence WHERE channel=?")
      .bind(CH)
      .first();
    expect(row.n).toBe(0);
  });
});
