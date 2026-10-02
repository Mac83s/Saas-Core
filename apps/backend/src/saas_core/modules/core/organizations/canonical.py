"""The one canonical JSON the platform hashes, signs and compares (ADR-076 §3).

Sorted keys, no whitespace, UTF-8 without escaping: the same bytes as the
blueprint catalog hash (ADR-046) and the content change-set digest (ADR-044).
It lives in core because the command registry hashes with it and core may not
import a shared module; shared modules delegate here instead of keeping a copy
whose bytes could drift from it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
