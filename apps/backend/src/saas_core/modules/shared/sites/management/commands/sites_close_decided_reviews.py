"""Closes the translation review items a page's editor left behind (TL16g).

Until the editor learned to tell the queue (`review_decided`, 2026-10-04), a
page's waiting language version accepted or rejected in the page's own editor
left its item open in „Tłumaczenia → Do akceptacji”: the page has nothing
waiting any more, so the item can be neither accepted nor discarded there and
counts in the tab for good. This closes what was orphaned before that, the way
the editor's decision closes it now — through the registry, so the item ends
`superseded` and, exactly as after a decision in the editor, every other open
item of the same page and language goes with it except the question whether
to take a translation down.

One-time and safe to repeat: a second run finds nothing. Look first:

    python manage.py sites_close_decided_reviews --dry-run
    python manage.py sites_close_decided_reviews

It prints one line per organization, page and language — identifiers only,
never a title or a text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from saas_core.content_protocol import registry
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from ...models import PageTranslation
from ...source_changes import PAGE_SOURCE_KEY


@dataclass(frozen=True, slots=True)
class _Sweep:
    """Whom the registry answers here: the clean-up, which reads what waits in
    one organization whoever could decide it."""

    organization_id: UUID
    membership_id: UUID | None = None
    actor_id: UUID | None = None
    principal_kind: str = "service"
    credential_id: UUID | None = None
    acting_via: str = ""
    acting_ref: str = ""
    acting_trigger: str = ""

    def has_permission(self, permission: str, /) -> bool:
        return True


def orphaned(sweep: _Sweep) -> list[tuple[UUID, str]]:
    """(page, language) pairs with a result waiting in the review queue and
    nothing waiting in the page — it was decided in the editor, or the page
    is gone."""
    waiting = set(
        PageTranslation.all_objects.filter(
            organization_id=sweep.organization_id,
            body_pending__isnull=False,
            page__deleted_at__isnull=True,
        ).values_list("page_id", "locale")
    )
    return sorted(
        (
            (object_id, locale)
            for source_key, object_id, locale in registry.waiting_reviews(sweep)
            if source_key == PAGE_SOURCE_KEY and (object_id, locale) not in waiting
        ),
        key=str,
    )


class Command(BaseCommand):
    help = "Zamyka pozycje „Do akceptacji”, których wersję rozstrzygnięto wcześniej w edytorze."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true", help="Tylko wypisuje, niczego nie zamyka."
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        dry_run = bool(options["dry_run"])
        found = 0
        for organization_id in billing_organization_ids():
            with transaction.atomic():
                set_local_organization_id(organization_id)
                sweep = _Sweep(organization_id)
                pairs = orphaned(sweep)
                if not dry_run:
                    for page_id, locale in pairs:
                        registry.review_decided(
                            context=sweep,
                            source_key=PAGE_SOURCE_KEY,
                            object_id=page_id,
                            locale=locale,
                        )
            for page_id, locale in pairs:
                self.stdout.write(f"{organization_id}\t{page_id}\t{locale}")
            found += len(pairs)
        self.stdout.write(
            f"Do zamknięcia: {found} (strona × język). Nic nie zmieniono."
            if dry_run
            else f"Zamknięto: {found} (strona × język)."
        )
