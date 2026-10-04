"""Reserved addresses never reach a mail provider (RFC 2606 / RFC 6761).

The demo seed addresses everybody in `.test`; a real SMTP provider would count
every such message as a bounce. `EMAIL_HOLD_RESERVED_DOMAINS` (default on)
makes the senders stop before the provider.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_RESERVED_TLDS = frozenset({"test", "example", "invalid", "localhost"})
_RESERVED_DOMAINS = frozenset({"example.com", "example.net", "example.org"})


def is_reserved_address(email: str) -> bool:
    _, at, domain = (email or "").strip().rpartition("@")
    labels = domain.lower().rstrip(".").split(".")
    if not at or not all(labels):
        return False
    if labels[-1] in _RESERVED_TLDS:
        return True
    return ".".join(labels[-2:]) in _RESERVED_DOMAINS


def holds_address(email: str) -> bool:
    """True when the setting is on and `email` is reserved; logs the domain only."""
    if not getattr(settings, "EMAIL_HOLD_RESERVED_DOMAINS", True) or not is_reserved_address(email):
        return False
    logger.info("mail held: reserved domain %s", email.rpartition("@")[2].strip().lower())
    return True
