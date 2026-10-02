"""One canonical JSON for every digest the platform compares (ADR-076 §3).

A consent digest, a change-set digest and a catalog hash are compared across
processes and stored in rows; if two copies of the serializer drifted by one
flag, a stored digest would stop matching and nothing would say why. The bytes
are pinned here, and the modules that kept their own copy now hand back the
core function itself.
"""

from __future__ import annotations

from saas_core.modules.core.organizations.canonical import canonical_json, canonical_json_hash
from saas_core.modules.shared.notifications import security
from saas_core.modules.shared.sites import models as sites_models

VALUE = {"zażółć": "gęślą jaźń", "b": [2, 1, {"y": None, "x": True}], "a": 1.5}


def test_bytes_are_sorted_compact_and_unescaped() -> None:
    assert canonical_json(VALUE) == (
        '{"a":1.5,"b":[2,1,{"x":true,"y":null}],"zażółć":"gęślą jaźń"}'.encode()
    )


def test_digest_is_pinned() -> None:
    assert (
        canonical_json_hash(VALUE)
        == "b44f43441a766b4867f6abbf6b2425b14ac1f3b141613a14643b8a2846502029"
    )


def test_key_order_does_not_change_the_digest() -> None:
    reordered = {"a": 1.5, "zażółć": "gęślą jaźń", "b": [2, 1, {"x": True, "y": None}]}
    assert canonical_json_hash(reordered) == canonical_json_hash(VALUE)


def test_sites_and_notifications_use_the_core_function() -> None:
    assert sites_models.canonical_json_hash is canonical_json_hash
    assert security.canonical_json is canonical_json
