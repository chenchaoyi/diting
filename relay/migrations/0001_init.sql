-- diting companion relay — D1 schema.
--
-- The relay is blind: it stores ciphertext envelopes + routing metadata
-- only. It never holds the secretbox key; per-channel auth is a hash of
-- the bearer token the producer/consumer derive from that key.

CREATE TABLE IF NOT EXISTS channels (
  channel      TEXT PRIMARY KEY,
  token_hash   TEXT NOT NULL,            -- sha256(bearer); trust-on-first-use
  apns_token   TEXT,                     -- consumer's APNs device token (nullable)
  apns_sandbox INTEGER NOT NULL DEFAULT 0,
  created      INTEGER NOT NULL          -- unix seconds
);

CREATE TABLE IF NOT EXISTS envelopes (
  channel TEXT NOT NULL,
  seq     INTEGER NOT NULL,              -- producer-assigned, monotonic per channel
  ts      TEXT NOT NULL,                 -- producer wall-clock (opaque to relay)
  body    TEXT NOT NULL,                 -- full envelope JSON (ciphertext inside)
  expiry  INTEGER NOT NULL,              -- unix seconds; row is dead past this
  PRIMARY KEY (channel, seq)             -- idempotent: retried POST is a no-op
);

CREATE INDEX IF NOT EXISTS idx_env_channel_seq ON envelopes (channel, seq);
CREATE INDEX IF NOT EXISTS idx_env_expiry ON envelopes (expiry);
