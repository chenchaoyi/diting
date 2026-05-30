// APNs token-based push from the Worker. The push is a content-free
// doorbell: a generic localizable alert plus the channel id and an
// optional coarse category. No real identifier (BSSID / SSID / device /
// IP) ever appears — the consumer pulls + decrypts and assembles the
// real notification text locally.

let _cachedJwt = null; // { token, iat }

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlStr(str) {
  return b64url(new TextEncoder().encode(str));
}

function pemToDer(pem) {
  const body = pem
    .replace(/-----BEGIN [^-]+-----/, "")
    .replace(/-----END [^-]+-----/, "")
    .replace(/\s+/g, "");
  const raw = atob(body);
  const der = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) der[i] = raw.charCodeAt(i);
  return der.buffer;
}

// Sign (and cache ~50 min) the APNs provider JWT (ES256 / P-256).
async function providerJwt(env) {
  const now = Math.floor(Date.now() / 1000);
  if (_cachedJwt && now - _cachedJwt.iat < 3000) return _cachedJwt.token;
  const header = b64urlStr(JSON.stringify({ alg: "ES256", kid: env.APNS_KEY_ID }));
  const claims = b64urlStr(JSON.stringify({ iss: env.APNS_TEAM_ID, iat: now }));
  const signingInput = `${header}.${claims}`;
  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToDer(env.APNS_KEY),
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign"],
  );
  // WebCrypto ECDSA returns the raw r||s concatenation JOSE expects.
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    new TextEncoder().encode(signingInput),
  );
  const jwt = `${signingInput}.${b64url(new Uint8Array(sig))}`;
  _cachedJwt = { token: jwt, iat: now };
  return jwt;
}

/** Content-free payload. `category` (optional) is a coarse hint only. */
export function buildPushPayload(channel, category) {
  const data = { ch: channel };
  if (category) data.c = category;
  return {
    aps: {
      alert: { "loc-key": "DITING_NEW_EVENTS" },
      sound: "default",
      "interruption-level": "active",
    },
    ...data,
  };
}

/** Best-effort send. Returns the APNs HTTP status (or 0 on transport error). */
export async function sendPush(env, deviceToken, sandbox, payload) {
  const host = sandbox
    ? "https://api.sandbox.push.apple.com"
    : env.APNS_HOST || "https://api.push.apple.com";
  try {
    const jwt = await providerJwt(env);
    const res = await fetch(`${host}/3/device/${deviceToken}`, {
      method: "POST",
      headers: {
        authorization: `bearer ${jwt}`,
        "apns-topic": env.APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
      },
      body: JSON.stringify(payload),
    });
    return res.status;
  } catch (_e) {
    return 0;
  }
}

// Test seam: drop the cached JWT.
export function _resetJwtCache() {
  _cachedJwt = null;
}
