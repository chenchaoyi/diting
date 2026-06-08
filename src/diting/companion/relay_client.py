"""Relay client — POST sealed envelopes, with a bounded offline queue.

``offer``-side code enqueues (cheap, never blocks the event loop);
``flush`` drains the queue to the relay in sequence order. A failed POST
stops the flush and leaves the rest queued, preserving order for the next
attempt — retries are safe because the relay is idempotent on ``seq``.
When the queue is full the oldest envelope is dropped and counted, so the
loss is reported rather than silent.

The HTTP call is injectable so the queue/flush logic is testable without
a network; the default transport is stdlib ``urllib`` (no new dependency).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

# (url, headers, body) -> HTTP status code; 0 means transport error.
Transport = Callable[[str, dict[str, str], bytes], int]
# (url, headers) -> response body bytes, or None on any error / non-2xx.
# Separate from Transport because presence is a GET that needs the body,
# while the producer path is a POST that only needs the status.
GetTransport = Callable[[str, dict[str, str]], "bytes | None"]

DEFAULT_MAX_QUEUE = 1000
CATEGORY_HEADER = "X-Diting-Category"
# Cloudflare's browser-integrity check rejects the default
# "Python-urllib" User-Agent with HTTP 403 (error 1010); send an explicit
# client UA so the relay (a CF Worker) accepts producer POSTs.
USER_AGENT = "diting-companion/1"


def urllib_transport(url: str, headers: dict[str, str], body: bytes) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


def urllib_get_transport(url: str, headers: dict[str, str]) -> "bytes | None":
    """GET ``url`` and return the response body, or None on any failure.

    Short timeout — the presence poll runs on a UI timer and must never
    block the screen; a slow/absent relay degrades to the "can't
    confirm" state rather than hanging."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 300:
                return resp.read()
            return None
    except (urllib.error.URLError, OSError):
        return None


@dataclass(frozen=True, slots=True)
class FlushReport:
    sent: int
    pending: int
    dropped: int


class RelayClient:
    def __init__(
        self,
        relay_url: str,
        channel: str,
        token: str,
        *,
        transport: Transport = urllib_transport,
        get_transport: GetTransport = urllib_get_transport,
        max_queue: int = DEFAULT_MAX_QUEUE,
    ) -> None:
        self._base = relay_url.rstrip("/")
        self._channel = channel
        self._token = token
        self._transport = transport
        self._get_transport = get_transport
        self._max = max_queue
        self._queue: deque[tuple[dict[str, Any], str | None, str | None]] = deque()
        self._dropped = 0
        self._consecutive_failures = 0

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def consecutive_failures(self) -> int:
        """Consecutive flushes that attempted delivery and sent nothing.
        Any successful send (even partial) resets it; a flush against an
        empty queue proves nothing and leaves it unchanged. The subtitle
        chip uses this to tell a sustained relay outage apart from a
        transient blip."""
        return self._consecutive_failures

    def enqueue(
        self,
        envelope: dict[str, Any],
        *,
        category: str | None = None,
        summary: str | None = None,
    ) -> None:
        if len(self._queue) >= self._max:
            self._queue.popleft()  # drop oldest — bounded, never silent
            self._dropped += 1
        self._queue.append((envelope, category, summary))

    def _url(self) -> str:
        return f"{self._base}/v1/channel/{quote(self._channel, safe='')}"

    def fetch_presence(self) -> "dict[str, Any] | None":
        """GET the channel's connected-phone count, or None on any
        failure. Returns the relay's ``{active, ttl_s, as_of}`` parsed
        from JSON. Count-only — carries no device identity. Never
        raises: a transport error, non-2xx, or unparseable body all
        degrade to None so the caller can show a "can't confirm" state
        rather than crash the screen."""
        headers = {
            "authorization": f"Bearer {self._token}",
            "user-agent": USER_AGENT,
        }
        raw = self._get_transport(f"{self._url()}/presence", headers)
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict) or not isinstance(obj.get("active"), int):
            return None
        return obj

    def _post(self, envelope: dict[str, Any], category: str | None, summary: str | None) -> int:
        headers = {
            "authorization": f"Bearer {self._token}",
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        }
        if category:
            headers[CATEGORY_HEADER] = category
        # The cleartext summary rides as a `push` sibling of the envelope;
        # the relay strips it before storing and shows it on the doorbell.
        payload: dict[str, Any] = envelope
        if summary or category:
            push: dict[str, str] = {}
            if summary:
                push["body"] = summary
            if category:
                push["category"] = category
            payload = {**envelope, "push": push}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self._transport(self._url(), headers, body)

    def flush(self) -> FlushReport:
        """Drain the queue in order until empty or a POST fails."""
        attempted = bool(self._queue)
        sent = 0
        while self._queue:
            envelope, category, summary = self._queue[0]
            status = self._post(envelope, category, summary)
            if 200 <= status < 300:
                self._queue.popleft()
                sent += 1
            else:
                break  # keep the rest queued in order; try again later
        if sent:
            self._consecutive_failures = 0
        elif attempted:
            self._consecutive_failures += 1
        return FlushReport(sent=sent, pending=len(self._queue), dropped=self._dropped)
