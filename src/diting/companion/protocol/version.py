"""Protocol version + back-compat tolerance.

The version is a single integer major. The rule mirrors the macOS-helper
schema rule: a newer producer adds fields additively within a major and
never changes the meaning of an existing field, so a consumer that knows
major N tolerates any payload stamped N. A payload stamped with an
unknown (newer) major is refused — abstained on — rather than processed.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1

# The set of protocol majors this build can decode. Today that is just
# {1}; when v2 lands, a build that still understands v1 lists {1, 2}.
SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})


def is_supported_version(version: object) -> bool:
    """True iff ``version`` is a protocol major this build can decode.

    Non-int input (a malformed or absent field) is unsupported, never a
    crash — callers abstain on False.
    """
    return isinstance(version, int) and not isinstance(version, bool) and (
        version in SUPPORTED_VERSIONS
    )
