# wifiscope dev tasks. Plain GNU make; no Python build steps live here
# (uv handles those). The targets exist mostly so contributors do not
# have to remember which language flag the preview script wants, and to
# keep the bilingual UI / docs workflow honest: a UI change always means
# regenerating BOTH preview SVGs.

.PHONY: help test test-all preview preview-en preview-zh helper

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test:  ## Run the pytest suite (109 cases)
	uv run pytest -q

test-all: test  ## Run pytest under both EN and ZH default-language settings
	WIFISCOPE_LANG=zh uv run pytest -q
	LANG=zh_CN.UTF-8 WIFISCOPE_LANG= uv run pytest -q

preview: preview-en preview-zh  ## Regenerate BOTH README preview SVGs (always run after a UI change)

preview-en:  ## Regenerate docs/preview.svg from the fake backend
	WIFISCOPE_LANG= uv run python docs/_capture_preview.py

preview-zh:  ## Regenerate docs/preview.zh.svg from the fake backend
	WIFISCOPE_LANG=zh uv run python docs/_capture_preview.py

helper:  ## Build the Swift Location-Services helper at helper/wifiscope-helper.app
	cd helper && ./build.sh
