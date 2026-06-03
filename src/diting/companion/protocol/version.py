"""Protocol version + back-compat tolerance.

The version is a single integer major. The rule mirrors the macOS-helper
schema rule: a newer producer adds fields additively within a major and
never changes the meaning of an existing field, so a consumer that knows
major N tolerates any payload stamped N. A payload stamped with an
unknown (newer) major is refused — abstained on — rather than processed.
"""

from __future__ import annotations

PROTOCOL_VERSION = 2

# The set of protocol majors this build can decode. A build that
# understands the v2 vocabulary (the `insight` event) still decodes every
# v1 envelope, so it lists {1, 2}. A v1-only peer lists {1} and abstains
# on v2 envelopes.
SUPPORTED_VERSIONS: frozenset[int] = frozenset({1, 2})

# Per-event minimum envelope version: the lowest protocol major that can
# decode an event of this type. Every type defined at v1 is omitted
# (default 1); `insight` was introduced at v2. The seal path stamps each
# envelope at its event's minimum version (``envelope_version_for``), so a
# v1-only consumer keeps receiving every existing event (still v1
# envelopes) and abstains ONLY on the v2 `insight` envelopes — graceful
# degradation across a desktop-updated-first skew, not a flag-day bump
# that would blind a v1 phone to all traffic.
EVENT_MIN_VERSION: dict[str, int] = {"insight": 2}


def envelope_version_for(event_type: object) -> int:
    """The minimum protocol major needed to decode ``event_type``.

    Unknown / non-str types fall back to ``1`` — a v1 envelope is the most
    broadly decodable; an unknown type is a producer bug we do not want to
    hide behind a higher version.
    """
    if isinstance(event_type, str):
        return EVENT_MIN_VERSION.get(event_type, 1)
    return 1


def is_supported_version(version: object) -> bool:
    """True iff ``version`` is a protocol major this build can decode.

    Non-int input (a malformed or absent field) is unsupported, never a
    crash — callers abstain on False.
    """
    return isinstance(version, int) and not isinstance(version, bool) and (
        version in SUPPORTED_VERSIONS
    )
