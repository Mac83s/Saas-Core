"""Lists addresses that took a reserved first segment before the rule (ADR-071).

A source-language page slug or a blog address may not be two letters (a
language prefix) or one of the platform's own paths. New ones are refused;
ones saved earlier keep answering, and a page "de" shadows the German home
page /de/ until somebody moves it. This shows where, per organization, so the
move is a decision with the owner rather than a silent rename.

    python manage.py sites_reserved_slugs
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from ...localization import first_segment_reserved
from ...models import ContentCollection, PageTranslation


class Command(BaseCommand):
    help = "Wypisuje adresy stron i blogów zajmujące zarezerwowany pierwszy segment."

    def handle(self, *_args: Any, **_options: Any) -> None:
        found = 0
        for organization_id in billing_organization_ids():
            with transaction.atomic():
                set_local_organization_id(organization_id)
                pages = (
                    PageTranslation.all_objects.filter(
                        organization_id=organization_id,
                        locale=F("site__default_locale"),
                        page__deleted_at__isnull=True,
                    )
                    .select_related("site", "page")
                    .order_by("site__slug", "slug")
                )
                rows = [
                    f"{organization_id}\t{item.site.slug}\tpage\t/{item.slug}/\t{item.page.key}"
                    for item in pages
                    if first_segment_reserved(item.slug)
                ]
                rows += [
                    f"{organization_id}\t{item.site.slug}\tcollection\t/{item.base_path}/\t{item.key}"
                    for item in ContentCollection.all_objects.filter(
                        organization_id=organization_id
                    ).select_related("site")
                    if first_segment_reserved(item.base_path)
                ]
            for row in rows:
                self.stdout.write(row)
            found += len(rows)
        self.stdout.write(f"Konflikty: {found}.")
