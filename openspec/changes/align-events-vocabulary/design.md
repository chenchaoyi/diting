# design — align-events-vocabulary

## Why bundle the two findings

Both findings are A1-era cleanup: the seen-side EN wording and
the filter-keys hint both got written when the cycle had five
buckets, before the three new transition event types were added.
They touch the same `i18n.py` / `tui.py` files and the same
spec section. Shipping them in one PR avoids a second
re-translation cycle for a one-string change.

## i18n key rename, not value-only edit

The catalog entries are `"device joined: "` → `"设备出现："`. The
ZH value is already correct. So the change is on the EN side —
the catalog key (which is also the EN-rendered string in
diting's i18n model).

The clean way to do this:

```python
# i18n.py — was
"device joined: ": "设备出现：",
"service joined: ": "服务出现：",
"host joined: ": "主机出现：",

# becomes
"device seen: ": "设备出现：",
"service seen: ": "服务出现：",
"host seen: ": "主机出现：",
```

Call sites at `tui.py:1947, 1970, 1993` flip from
`t("device joined: ")` → `t("device seen: ")` etc.

If any old build reads a JSONL log produced by a new build,
the analyzer is locale-stable English keys (`ble_device_seen`)
— the renamed UI string never enters the log. No back-compat
concern there.

## Filter-keys hint wording

Current: `Press 1/2/3/4/0 to filter; m or Esc to close`.

Three options for the extended form:

1. **Explicit:** `Press 1/2/3/4/5/6/7/0 to filter; m or Esc to close`
2. **Range:** `Press 1–7 to filter, 0 to clear; m or Esc to close`
3. **Implicit:** `Press 1–7/0 to filter; m or Esc to close`

(1) is the obvious extension and what the audit recommended.
(2) and (3) are more compact, but `1–7` is less mechanically
discoverable than the keys-as-digits list — a user scanning the
footer for which key sets `lan` does not learn that 7 is the
answer without trying. (1) wins on user discoverability.

Same expansion applies to the help-modal prose at
`tui.py:612` / `i18n.py:880, 886`. ZH counterpart at
`i18n.py:1249` likewise.

## What the spec MUST change

`openspec/specs/tui-shell/spec.md:135-147` lists the seven A1
types' rendered formats with `device joined` / `service joined`
/ `host joined`. Three bullets and one scenario example flip
to `seen`. Everything else in the requirement stays.

The filter-cycle requirement at `spec.md:96-117` is already
correct (it lists the eight buckets and the scenarios). The
audit-finding is about the prose hint, not the spec — no spec
change needed for finding #2.

## Test changes

Three string-only flips in `test_tui_helpers.py`:

- `:2659` `assert "device joined" in text` → `assert "device seen" in text`
- `:2692` `assert "service joined" in text` → `assert "service seen" in text`
- `:2725` `assert "host joined" in text` → `assert "host seen" in text`

No new tests needed for the i18n side — the existing tests
exercise the formatter end-to-end.

For finding #2, the audit recommends no new test — the prose
itself is review-enforced (per TESTING.md row 362 for EN, 353
for ZH: "HelpScreen content review-enforced"). Adding a
string-pinning test would couple the test to specific phrasing
that may drift later; not worth the maintenance cost.

## What this change does NOT touch

- The JSONL `type` field. Already locale-stable English.
- The `tui-shell` filter-cycle requirement (unchanged — only
  the prose-hint is stale, not the spec).
- The `events` capability spec. Untouched.
- The analyzer or any cross-session aggregation. Unaffected.
- ZH catalog values. Already correct.
