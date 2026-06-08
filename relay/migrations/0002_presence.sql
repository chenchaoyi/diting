-- diting companion relay — channel presence (connected-phone count).
--
-- Privacy-light: tracks only an OPAQUE per-connection hash per channel,
-- never a device identity. `puller` is sha256(channel + ":" + ip) and
-- is non-reversible to the IP without it; rows carry a short TTL via
-- `last_seen` and are lazy-pruned on read. The relay still cannot tell
-- one phone from another beyond connection distinctness, and stores
-- nothing identifying.

CREATE TABLE IF NOT EXISTS presence (
  channel   TEXT NOT NULL,
  puller    TEXT NOT NULL,             -- opaque sha256(channel + ':' + ip)
  last_seen INTEGER NOT NULL,          -- unix seconds; presence past TTL is dead
  PRIMARY KEY (channel, puller)        -- idempotent: repeat pulls upsert one row
);

CREATE INDEX IF NOT EXISTS idx_presence_channel_seen ON presence (channel, last_seen);
