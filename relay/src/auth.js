// Per-channel auth. The bearer token is derived (HMAC-SHA256 of the
// channel key) on the producer + consumer; the relay only ever sees the
// token and stores sha256(token), so a relay DB leak reveals neither the
// key nor a replayable bearer. Mirrors diting.companion.protocol.auth.

/** Hex sha256 of the bearer token — what we persist per channel. */
export async function tokenHash(token) {
  const data = new TextEncoder().encode(token);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Constant-time string compare (equal-length hex hashes). */
export function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) {
    return false;
  }
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

/** Extract the Bearer token from an Authorization header, or null. */
export function bearer(request) {
  const h = request.headers.get("authorization") || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1] : null;
}
