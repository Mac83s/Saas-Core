"""Notifications' part of the demo (core/organizations/demo.py): how many
messages a run queued.

The seed sends what the product sends — a booking's confirmation, a transfer's
details, a refund's notice — because it goes through the same services. Every
address is in `.test`, and `EMAIL_HOLD_RESERVED_DOMAINS` (default on) stops mail
to reserved domains before any provider, so nothing leaves the host; a developer's
stack sets it off and the messages land in Mailpit.
The scenarios keep the number small (customers of the past have a phone and no
e-mail), and the run says the number, per company.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from saas_core.modules.core.organizations.context import set_local_organization_id

from .models import NotificationMessage

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRun

_MEMO = "notifications.messages"


def _counts(run: DemoRun) -> dict[str, int]:
    counts = {}
    for key, organization in run.organizations.items():
        with transaction.atomic():
            set_local_organization_id(organization.id)
            counts[key] = NotificationMessage.all_objects.filter(
                organization_id=organization.id
            ).count()
    return counts


def count_before(run: DemoRun) -> None:
    run.memo[_MEMO] = _counts(run)


def report(run: DemoRun) -> None:
    before = run.memo.get(_MEMO, {})
    total = 0
    for key, count in _counts(run).items():
        queued = count - before.get(key, 0)
        total += queued
        if queued:
            run.log(f"+ e-maile {run.spec(key).name}: {queued}")
    run.log(
        f"{'+' if total else '='} e-maile w tym uruchomieniu: {total} "
        "(wszystkie na adresy .test; lokalnie trafiają do Mailpita)"
    )
