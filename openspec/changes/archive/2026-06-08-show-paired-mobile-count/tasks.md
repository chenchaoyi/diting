# show-paired-mobile-count — tasks

## 1. Test plan first

- [x] 1.1 TESTING.md rows (EN) for relay presence + desktop count line
- [x] 1.2 Mirror in docs/zh/TESTING.md
- [x] 1.3 Failing tests: relay (pull registers; decays after TTL;
      dedupes repeat pulls; presence read doesn't self-count; 403 on
      bad token) + python (`fetch_presence` parses ok / None on error;
      presence-line render for connected / zero / error / loading)

## 2. Relay

- [x] 2.1 `migrations/0002_presence.sql` — presence table
- [x] 2.2 `handlePull` upserts presence (opaque salted cf-connecting-ip
      hash, TTL 90s) + lazy-prune
- [x] 2.3 `handlePresence` + route `GET /v1/channel/{id}/presence` →
      `{active, ttl_s, as_of}`
- [x] 2.4 relay vitest cases

## 3. Desktop

- [x] 3.1 `RelayClient.fetch_presence()` (GET transport, returns dict
      or None)
- [x] 3.2 `_format_presence_line(state)` pure renderer — connected /
      zero / error / loading, semantic colour, relative as_of
- [x] 3.3 i18n EN keys + ZH values (singular/plural en)
- [x] 3.4 `CompanionScreen` poll timer (start on_mount, stop on
      unmount) + render line under the QR

## 4. Verify

- [x] 4.1 `uv run pytest`
- [x] 4.2 `uv run python scripts/tui_snapshot.py --mode regression`
- [x] 4.3 `openspec validate --specs --strict` +
      `openspec validate show-paired-mobile-count --strict`
- [x] 4.4 relay `npm test` (best-effort — may need registry/runtime)
