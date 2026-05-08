# wifiscope dev tasks. Plain GNU make; no Python build steps live here
# (uv handles those). The targets exist mostly so contributors do not
# have to remember which language flag the preview script wants, and to
# keep the bilingual UI / docs workflow honest: a UI change always means
# regenerating BOTH preview SVGs.

.PHONY: help test test-all preview preview-en preview-zh preview-ble preview-ble-en preview-ble-zh preview-events preview-events-en preview-events-zh helper monitor snapshot update-vendors

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test:  ## Run the pytest suite
	uv run pytest -q

test-all: test  ## Run pytest under both EN and ZH default-language settings
	WIFISCOPE_LANG=zh uv run pytest -q
	LANG=zh_CN.UTF-8 WIFISCOPE_LANG= uv run pytest -q

preview: preview-en preview-zh preview-ble-en preview-ble-zh preview-events-en preview-events-zh  ## Regenerate ALL preview SVGs (Wi-Fi + BLE + Events modal, EN + ZH)

preview-en:  ## Regenerate docs/preview.svg (Wi-Fi view, English)
	WIFISCOPE_LANG= WIFISCOPE_PREVIEW_VIEW=wifi uv run python docs/_capture_preview.py

preview-zh:  ## Regenerate docs/preview.zh.svg (Wi-Fi view, Chinese)
	WIFISCOPE_LANG=zh WIFISCOPE_PREVIEW_VIEW=wifi uv run python docs/_capture_preview.py

preview-ble-en:  ## Regenerate docs/preview-ble.svg (BLE view, English)
	WIFISCOPE_LANG= WIFISCOPE_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py

preview-ble-zh:  ## Regenerate docs/preview-ble.zh.svg (BLE view, Chinese)
	WIFISCOPE_LANG=zh WIFISCOPE_PREVIEW_VIEW=ble uv run python docs/_capture_preview.py

preview-events-en:  ## Regenerate docs/preview-events.svg (Events modal, English)
	WIFISCOPE_LANG= WIFISCOPE_PREVIEW_VIEW=events uv run python docs/_capture_preview.py

preview-events-zh:  ## Regenerate docs/preview-events.zh.svg (Events modal, Chinese)
	WIFISCOPE_LANG=zh WIFISCOPE_PREVIEW_VIEW=events uv run python docs/_capture_preview.py

helper:  ## Build the Swift helper at helper/wifiscope-helper.app
	cd helper && ./build.sh

monitor:  ## Run wifiscope monitor (headless JSONL events; Ctrl+C to quit)
	uv run wifiscope monitor

snapshot:  ## Drive the TUI through designed scenarios + capture screenshots
	uv run wifiscope snapshot --out-dir snapshot-output

update-vendors:  ## Refresh src/wifiscope/data/bluetooth_vendors.json from Bluetooth SIG
	uv run python scripts/update_vendors.py
