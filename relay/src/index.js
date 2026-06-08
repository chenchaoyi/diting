// diting companion relay — end-to-end-encrypted store-and-forward.
//
// The relay forwards ciphertext envelopes between a diting desktop
// producer and a paired diting-mobile consumer, and rings an APNs
// doorbell when new envelopes land. It never holds the secretbox key and
// cannot read event content. See companion-protocol (canonical in the
// diting repo) for the wire contract.

import { bearer, timingSafeEqual, tokenHash } from "./auth.js";
import { buildPushPayload, sendPush } from "./apns.js";

const SUPPORTED_VERSIONS = new Set([1]);
const CATEGORIES = new Set(["link", "ble", "lan", "bonjour", "env"]);

// Channel-presence window. ≥ 2× the mobile pull cadence so one missed
// poll doesn't drop a phone from the connected count.
const PRESENCE_TTL_SECONDS = 90;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });

const nowSec = () => Math.floor(Date.now() / 1000);

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function validateEnvelope(obj, channelId) {
  if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
    throw new HttpError(400, "envelope must be an object");
  }
  for (const k of ["v", "ch", "seq", "ts", "n", "ct"]) {
    if (!(k in obj)) throw new HttpError(400, `envelope missing '${k}'`);
  }
  if (!SUPPORTED_VERSIONS.has(obj.v)) {
    throw new HttpError(400, `unsupported protocol version: ${obj.v}`);
  }
  if (obj.ch !== channelId) throw new HttpError(400, "envelope 'ch' != path");
  if (!Number.isInteger(obj.seq) || obj.seq < 1) {
    throw new HttpError(400, "envelope 'seq' must be an integer >= 1");
  }
  for (const k of ["ts", "n", "ct"]) {
    if (typeof obj[k] !== "string" || !obj[k]) {
      throw new HttpError(400, `envelope '${k}' must be a non-empty string`);
    }
  }
}

// Opaque, per-channel, non-reversible dedupe key for a pulling phone.
// All phones on a channel share the bearer token, so the token can't
// separate them — but the Worker has the connection IP. We hash it with
// the channel as salt and NEVER store the IP. Phones behind one NAT
// collapse to a single entry (undercount); we never store identity.
// When the IP is absent (local/test), a fixed sentinel makes any pull
// register as one puller.
async function pullerKey(channelId, request) {
  const ip = request.headers.get("cf-connecting-ip") || "local";
  const data = new TextEncoder().encode(`${channelId}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function getChannel(env, channelId) {
  return env.DB.prepare(
    "SELECT channel, token_hash, apns_token, apns_sandbox FROM channels WHERE channel=?",
  )
    .bind(channelId)
    .first();
}

// Trust-on-first-use: bind the channel to this bearer's hash if new,
// else require the hash to match. Returns the (existing or freshly
// created) channel row. Throws 401/403 on auth failure.
async function authorizeOrBind(env, channelId, request) {
  const token = bearer(request);
  if (!token) throw new HttpError(401, "missing bearer token");
  const hash = await tokenHash(token);
  const row = await getChannel(env, channelId);
  if (!row) {
    await env.DB.prepare(
      "INSERT INTO channels (channel, token_hash, created) VALUES (?, ?, ?)",
    )
      .bind(channelId, hash, nowSec())
      .run();
    return { channel: channelId, token_hash: hash, apns_token: null, apns_sandbox: 0 };
  }
  if (!timingSafeEqual(row.token_hash, hash)) throw new HttpError(403, "forbidden");
  return row;
}

// Read paths must not create channels: an unknown channel is a 404.
async function authorizeExisting(env, channelId, request) {
  const token = bearer(request);
  if (!token) throw new HttpError(401, "missing bearer token");
  const row = await getChannel(env, channelId);
  if (!row) throw new HttpError(404, "unknown channel");
  const hash = await tokenHash(token);
  if (!timingSafeEqual(row.token_hash, hash)) throw new HttpError(403, "forbidden");
  return row;
}

async function handleStore(env, ctx, channelId, request) {
  let body;
  try {
    body = await request.json();
  } catch {
    throw new HttpError(400, "body is not JSON");
  }
  // A cleartext push summary may ride alongside the sealed envelope as a
  // `push` sibling. Strip it before validation/storage — only the
  // encrypted envelope is ever persisted or returned to the consumer.
  const push = body && typeof body === "object" ? body.push : undefined;
  if (push !== undefined && body && typeof body === "object") delete body.push;
  const envelope = body;
  validateEnvelope(envelope, channelId);
  const row = await authorizeOrBind(env, channelId, request);

  const ttl = Number(env.TTL_SECONDS) || 604800;
  await env.DB.prepare(
    "INSERT INTO envelopes (channel, seq, ts, body, expiry) VALUES (?, ?, ?, ?, ?) " +
      "ON CONFLICT(channel, seq) DO NOTHING",
  )
    .bind(channelId, envelope.seq, envelope.ts, JSON.stringify(envelope), nowSec() + ttl)
    .run();

  // Ring the doorbell, best-effort, off the response path.
  if (row.apns_token) {
    const hint = (push && push.category) || request.headers.get("x-diting-category");
    const category = CATEGORIES.has(hint) ? hint : undefined;
    const detail = push && typeof push.body === "string" ? push.body : undefined;
    const payload = buildPushPayload(channelId, category, detail);
    ctx.waitUntil(sendPush(env, row.apns_token, !!row.apns_sandbox, payload));
  }
  return json({ ok: true, seq: envelope.seq });
}

async function handlePull(env, channelId, url, request) {
  await authorizeExisting(env, channelId, request);
  // The phone's authenticated pull is the presence heartbeat: upsert an
  // opaque per-connection key so the desktop can show a connected count.
  // Only /pull registers presence — /presence (the desktop poll) never
  // does, so the desktop reading the count cannot inflate it.
  const puller = await pullerKey(channelId, request);
  await env.DB.prepare(
    "INSERT INTO presence (channel, puller, last_seen) VALUES (?, ?, ?) " +
      "ON CONFLICT(channel, puller) DO UPDATE SET last_seen=excluded.last_seen",
  )
    .bind(channelId, puller, nowSec())
    .run();
  const since = Number.parseInt(url.searchParams.get("since") || "0", 10) || 0;
  const limit = Number(env.MAX_PULL) || 500;
  const now = nowSec();
  // Lazy purge expired rows for this channel, then read live ones.
  await env.DB.prepare("DELETE FROM envelopes WHERE channel=? AND expiry<=?")
    .bind(channelId, now)
    .run();
  const { results } = await env.DB.prepare(
    "SELECT seq, body FROM envelopes WHERE channel=? AND seq>? AND expiry>? " +
      "ORDER BY seq ASC LIMIT ?",
  )
    .bind(channelId, since, now, limit)
    .all();
  const envelopes = results.map((r) => JSON.parse(r.body));
  const cursor = envelopes.length ? envelopes[envelopes.length - 1].seq : since;
  return json({ envelopes, cursor });
}

// Count-only channel presence. Read-only: does NOT register the caller
// as a puller (only /pull does), so a desktop polling this never inflates
// the count. Lazy-prunes expired rows, then counts the live ones. Returns
// no device identity — just a number, the window width, and a timestamp.
async function handlePresence(env, channelId, request) {
  await authorizeExisting(env, channelId, request);
  const now = nowSec();
  const cutoff = now - PRESENCE_TTL_SECONDS;
  await env.DB.prepare("DELETE FROM presence WHERE channel=? AND last_seen<=?")
    .bind(channelId, cutoff)
    .run();
  const row = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM presence WHERE channel=? AND last_seen>?",
  )
    .bind(channelId, cutoff)
    .first();
  return json({
    active: (row && row.n) || 0,
    ttl_s: PRESENCE_TTL_SECONDS,
    as_of: new Date(now * 1000).toISOString(),
  });
}

async function handleRegisterApns(env, channelId, request) {
  let body;
  try {
    body = await request.json();
  } catch {
    throw new HttpError(400, "body is not JSON");
  }
  if (typeof body.token !== "string" || !body.token) {
    throw new HttpError(400, "missing apns 'token'");
  }
  await authorizeOrBind(env, channelId, request);
  await env.DB.prepare(
    "UPDATE channels SET apns_token=?, apns_sandbox=? WHERE channel=?",
  )
    .bind(body.token, body.sandbox ? 1 : 0, channelId)
    .run();
  return json({ ok: true });
}

async function handleUnpair(env, channelId, request) {
  await authorizeExisting(env, channelId, request);
  await env.DB.prepare("DELETE FROM envelopes WHERE channel=?").bind(channelId).run();
  await env.DB.prepare("DELETE FROM presence WHERE channel=?").bind(channelId).run();
  await env.DB.prepare("DELETE FROM channels WHERE channel=?").bind(channelId).run();
  return json({ ok: true });
}

async function route(request, env, ctx) {
  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean); // ["v1","channel",":id",...]
  if (parts.length === 0) return new Response("diting companion relay\n");
  if (parts[0] !== "v1" || parts[1] !== "channel" || !parts[2]) {
    throw new HttpError(404, "not found");
  }
  const channelId = decodeURIComponent(parts[2]);
  const sub = parts[3];

  if (!sub) {
    if (request.method === "POST") return handleStore(env, ctx, channelId, request);
    if (request.method === "GET") return handlePull(env, channelId, url, request);
    if (request.method === "DELETE") return handleUnpair(env, channelId, request);
    throw new HttpError(405, "method not allowed");
  }
  if (sub === "apns" && request.method === "POST") {
    return handleRegisterApns(env, channelId, request);
  }
  if (sub === "presence" && request.method === "GET") {
    return handlePresence(env, channelId, request);
  }
  throw new HttpError(404, "not found");
}

export default {
  async fetch(request, env, ctx) {
    try {
      return await route(request, env, ctx);
    } catch (e) {
      if (e instanceof HttpError) return json({ error: e.message }, e.status);
      return json({ error: "internal error" }, 500);
    }
  },
};
