"""Nothing reaches the pre-tenant connection by accident.

ADR-041 opens a second database identity for the handful of reads that happen
before anybody knows which tenant is asking. Its whole value is that the list
of those reads can be written down, so the router refuses to send anything
there on its own: a query uses it only by naming it, and migrations never run
on it at all.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings


class PreTenantRouter:
    def db_for_read(self, model: type[Any], **hints: Any) -> str | None:
        del model, hints
        return None

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        del model, hints
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        del obj1, obj2, hints
        # One database behind both aliases, so a relation is always fine.
        return True

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool | None:
        del app_label, hints
        alias = settings.PRE_TENANT_DATABASE_ALIAS
        # In tests both names point at the same connection, and refusing to
        # migrate it would leave an empty database rather than a safe one.
        if alias != "default" and db == alias:
            return False
        return None
