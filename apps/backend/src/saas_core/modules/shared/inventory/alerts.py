"""The daily low-stock notice (warehouse plan phase 10, settings plan M4).

Off until a company switches it on (`inventory.alerts.low_stock`, coordinator's
decision 03.10: nothing was sent before, so nothing starts being sent by a
deploy). Then, once per day of the company — the first hourly run at or after
its hour (`inventory.alerts.hour`) that finds anything at or below its
minimum — the people it names hear in the panel and by e-mail what to refill.
The key is the company's local date, so the hour that repeats when the clocks
go back sends nothing twice, and the hour that is skipped when they go forward
skips no day.

The e-mail names items and places, never people: whose kit it is stays in the
panel. Companies one at a time, each inside its own tenant (ADR-039).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.identity.models import UserStatus
from saas_core.modules.core.organizations.api import setting
from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    current_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus, Organization
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    billing_organization_ids,
    decide_feature,
)
from saas_core.modules.shared.notifications.api import (
    AUDIENCE_STAFF,
    EmailTemplate,
    notify_in_app,
    queue_email,
    register_email_template,
    staff_locale,
)

from .company_settings import HOLDER, HOUR, INVENTORY_ENABLED, LOW_STOCK, PLACES, RECIPIENTS
from .models import LocationKind
from .permissions import INVENTORY_MANAGE
from .services import low_stock_rows

LOW_STOCK_NOTICE = "inventory.low_stock"
NOTIFY_ROLE = "inventory_notifications"
#: How many items a notice names; the rest is „and N more” — the panel has all.
NAMED = 5
PANEL_PATH = "/panel/inventory?low=1"

UNITS = {
    "pl": {"piece": "szt.", "pack": "opak.", "hour": "godz."},
    "en": {"piece": "pcs", "pack": "packs", "hour": "h"},
}


@contextmanager
def _as_the_organization(organization_id: UUID) -> Iterator[None]:
    outer = current_tenant_context()
    if outer is not None and outer.organization_id == organization_id:
        yield
        return
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=NOTIFY_ROLE,
        permissions=frozenset(),
        principal_kind="service",
    )
    with activate_tenant_context(context):
        yield


def _panel(locale: str) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/") + ("/en" if locale == "en" else "")
    return f"{base}{PANEL_PATH}"


def _amount(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _items(rows: Sequence[dict[str, Any]], locale: str) -> str:
    units = UNITS.get(locale, UNITS["pl"])
    named = [
        f"{row['item_name']} — {row['location_name']}: {_amount(row['available'])} / "
        f"{_amount(row['minimum'])} {units.get(row['unit'], row['unit'])}"
        for row in rows[:NAMED]
    ]
    more = len(rows) - NAMED
    if more > 0:
        named.append(f"i {more} więcej" if locale == "pl" else f"and {more} more")
    return "; ".join(named)


def _payload(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Facts for the panel's sentence: the count and the first items."""
    return {
        "count": len(rows),
        "items": [
            {
                "item_id": str(row["item_id"]),
                "name": row["item_name"],
                "location_id": str(row["location_id"]),
                "available": _amount(row["available"]),
                "minimum": _amount(row["minimum"]),
                "unit": row["unit"],
            }
            for row in rows[:NAMED]
        ],
    }


def _recipients(
    organization_id: UUID, rows: Sequence[dict[str, Any]]
) -> list[tuple[Any, list[dict[str, Any]]]]:
    """(user, the rows they hear about): the warehouse's people — or the owner
    alone — get every row; a holder, when the company says so, their own."""
    memberships = list(
        Membership.objects.select_related("role", "user").filter(
            organization_id=organization_id,
            status=MembershipStatus.ACTIVE,
            user__status=UserStatus.ACTIVE,
        )
    )
    if setting(RECIPIENTS, organization_id=organization_id) == "owner":
        everything = [m.user for m in memberships if m.role.key == "owner"]
    else:
        everything = [m.user for m in memberships if INVENTORY_MANAGE in (m.role.permissions or ())]
    chosen: dict[UUID, tuple[Any, list[dict[str, Any]]]] = {
        user.id: (user, list(rows)) for user in everything
    }
    if setting(PLACES, organization_id=organization_id) == "all" and setting(
        HOLDER, organization_id=organization_id
    ):
        members = {m.user_id: m.user for m in memberships}
        whole = set(chosen)
        for row in rows:
            holder = row["holder_id"]
            if (
                row["location_kind"] == LocationKind.PERSON
                and holder in members
                and holder not in whole
            ):
                chosen.setdefault(holder, (members[holder], []))[1].append(row)
    return list(chosen.values())


def _due(organization: Organization, now: datetime) -> str | None:
    """The company's local date when its notice may go out now, else None."""
    local = timezone.localtime(now, ZoneInfo(organization.timezone))
    if local.hour < int(setting(HOUR, organization_id=organization.id)):
        return None
    return local.date().isoformat()


def notify_low_stock(now: datetime | None = None) -> int:
    """Every hour: each company that wants it hears once a day what to refill.
    Returns how many people were told for the first time today."""
    now = now or timezone.now()
    told = 0
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            if setting(LOW_STOCK, organization_id=organization_id) != "daily":
                continue
            with _as_the_organization(organization_id):
                # A plan without the warehouse keeps the choice, not the notice.
                if not decide_feature(INVENTORY_ENABLED, operation=FeatureOperation.READ).allowed:
                    continue
            organization = Organization.objects.get(pk=organization_id)
            day = _due(organization, now)
            if day is None:
                continue
            rows = low_stock_rows(organization_id, setting(PLACES, organization_id=organization_id))
            if not rows:
                continue
            told += _tell(organization, day, rows)
    return told


def _tell(organization: Organization, day: str, rows: Sequence[dict[str, Any]]) -> int:
    key = f"inventory-low:{organization.id}:{day}"
    told = 0
    with _as_the_organization(organization.id):
        for user, own in _recipients(organization.id, rows):
            if not notify_in_app(
                organization_id=organization.id,
                user_id=user.id,
                kind=LOW_STOCK_NOTICE,
                payload=_payload(own),
                idempotency_key=key,
            ):
                continue  # Told already today.
            told += 1
            locale = staff_locale(organization_id=organization.id, user=user)
            queue_email(
                recipient_email=user.email,
                template_key=LOW_STOCK_NOTICE,
                template_version=1,
                locale=locale,
                template_context={
                    "organization_name": organization.name,
                    "count": str(len(own)),
                    "items": _items(own, locale),
                    "panel_url": _panel(locale),
                },
                idempotency_key=f"{key}:{user.id}",
                causation_id=f"inventory_low_stock:{day}",
                recipient_user=user,
            )
    return told


def register_templates() -> None:
    """The mail of the daily notice; from `ready()`."""
    register_email_template(
        EmailTemplate(
            key=LOW_STOCK_NOTICE,
            version=1,
            category="required",
            subjects={
                "pl": "Magazyn: {count} do uzupełnienia",
                "en": "Warehouse: {count} to refill",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: tyle pozycji jest na minimum albo poniżej — "
                    "{count}.</p><p>{items}</p>"
                    '<p><a href="{panel_url}">Zobacz w magazynie</a></p>'
                    "<p>Powiadomienie wyłączysz w Ustawieniach › Magazyn.</p>"
                ),
                "en": (
                    "<p>{organization_name}: {count} items are at or below their minimum."
                    "</p><p>{items}</p>"
                    '<p><a href="{panel_url}">See them in the warehouse</a></p>'
                    "<p>You can switch this notice off in Settings › Warehouse.</p>"
                ),
            },
            allowed_context=frozenset({"organization_name", "count", "items", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
