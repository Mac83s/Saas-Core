"""Lists addresses that took a reserved segment before the rule (ADR-071).

A source-language page slug or a blog address may not be two letters (a
language prefix) or one of the platform's own paths, and neither they nor a
language version's slug may be a record source's name of its section
(ADR-074 pkt 7; a page may where the source gives it the section's own
address). New ones are refused; ones saved earlier keep answering and saving,
and a page "de" shadows the German home page /de/ until somebody moves it.
This shows where, per organization, so the move is a decision with the owner
rather than a silent rename.

    python manage.py sites_reserved_slugs
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.billing.api import billing_organization_ids

from ...localization import first_segment_reserved, localized_path, page_slug_reserved
from ...models import ContentCollection, PageTranslation


class Command(BaseCommand):
    help = "Wypisuje adresy stron i blogów zajmujące zarezerwowany segment."

    def handle(self, *_args: Any, **_options: Any) -> None:
        found = 0
        for organization_id in billing_organization_ids():
            with transaction.atomic():
                set_local_organization_id(organization_id)
                # A page's address in every language it has one in.
                pages = (
                    PageTranslation.all_objects.filter(
                        organization_id=organization_id,
                        page__deleted_at__isnull=True,
                    )
                    .select_related("site", "page")
                    .order_by("site__slug", "slug", "locale")
                )
                rows = [
                    "\t".join((
                        str(organization_id),
                        item.site.slug,
                        "page",
                        localized_path(
                            default_locale=item.site.default_locale,
                            locale=item.locale,
                            slug=item.slug,
                        ),
                        item.page.key,
                    ))
                    for item in pages
                    if page_slug_reserved(
                        item.slug, default_locale=item.site.default_locale, locale=item.locale
                    )
                ]
                rows += [
                    f"{organization_id}\t{item.site.slug}\tcollection\t{path}\t{item.key}"
                    for item in ContentCollection.all_objects.filter(
                        organization_id=organization_id
                    ).select_related("site")
                    # Its name in the site's language and in each language
                    # that names it differently (ADR-071 pkt 14).
                    for path in (
                        f"/{item.base_path}/",
                        *(
                            f"/{locale}/{name}/"
                            for locale, name in sorted((item.locale_paths or {}).items())
                        ),
                    )
                    if first_segment_reserved(path.strip("/").rsplit("/", 1)[-1])
                ]
            for row in rows:
                self.stdout.write(row)
            found += len(rows)
        self.stdout.write(f"Konflikty: {found}.")
