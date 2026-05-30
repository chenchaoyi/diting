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
        max_queue: int = DEFAULT_MAX_QUEUE,
    ) -> None:
        self._base = relay_url.rstrip("/")
        self._channel = channel
        self._token = token
        self._transport = transport
        self._max = max_queue
        self._queue: deque[tuple[dict[str, Any], str | None]] = deque()
        self._dropped = 0

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def dropped(self) -> int:
        return self._dropped

    def enqueue(self, envelope: dict[str, Any], *, category: str | None = None) -> None:
        if len(self._queue) >= self._max:
            self._queue.popleft()  # drop oldest — bounded, never silent
            self._dropped += 1
        self._queue.append((envelope, category))

    def _url(self) -> str:
        return f"{self._base}/v1/channel/{quote(self._channel, safe='')}"

    def _post(self, envelope: dict[str, Any], category: str | None) -> int:
        headers = {
            "authorization": f"Bearer {self._token}",
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        }
        if category:
            headers[CATEGORY_HEADER] = category
        body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        return self._transport(self._url(), headers, body)

    def flush(self) -> FlushReport:
        """Drain the queue in order until empty or a POST fails."""
        sent = 0
        while self._queue:
            envelope, category = self._queue[0]
            status = self._post(envelope, category)
            if 200 <= status < 300:
                self._queue.popleft()
                sent += 1
            else:
                break  # keep the rest queued in order; try again later
        return FlushReport(sent=sent, pending=len(self._queue), dropped=self._dropped)
