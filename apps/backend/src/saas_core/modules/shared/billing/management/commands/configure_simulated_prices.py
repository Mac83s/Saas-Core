from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saas_core.modules.shared.billing.models import Plan, StripePriceMapping


class Command(BaseCommand):
    help = "Configure deterministic local Price mappings for the billing simulator."

    def handle(self, *args: Any, **options: Any) -> None:
        del args, options
        if settings.BILLING_PROVIDER != "simulated":
            raise CommandError("Komenda wymaga BILLING_PROVIDER=simulated.")
        if settings.STRIPE_LIVEMODE:
            raise CommandError("Symulator płatności nie obsługuje trybu live.")

        plans_by_key = {
            plan.key: plan
            for plan in Plan.objects.filter(
                key__in=settings.BILLING_PLAN_KEYS,
                is_active=True,
                is_public=True,
                current_version__isnull=False,
            ).select_related("current_version")
        }
        missing = [key for key in settings.BILLING_PLAN_KEYS if key not in plans_by_key]
        if missing:
            raise CommandError(
                "Brak aktywnej bieżącej wersji planów: " + ", ".join(missing) + "."
            )

        configured = 0
        unchanged = 0
        with transaction.atomic():
            for plan_key in settings.BILLING_PLAN_KEYS:
                plan = plans_by_key[plan_key]
                version = plan.current_version
                if version is None:  # Query and missing check enforce this contract.
                    raise CommandError(f"Plan {plan_key!r} nie ma bieżącej wersji.")
                product_id = f"sim_prod_{plan.key}"
                price_id = f"sim_price_{plan.key}_v{version.version}"
                active = (
                    StripePriceMapping.objects.select_for_update()
                    .filter(plan_version=version, livemode=False, is_active=True)
                    .first()
                )
                if (
                    active is not None
                    and active.stripe_product_id == product_id
                    and active.stripe_price_id == price_id
                ):
                    unchanged += 1
                    continue
                if active is not None:
                    active.is_active = False
                    active.save(update_fields=["is_active", "updated_at"])

                replacement = StripePriceMapping.objects.filter(
                    stripe_price_id=price_id,
                ).first()
                if replacement is None:
                    StripePriceMapping.objects.create(
                        plan_version=version,
                        stripe_product_id=product_id,
                        stripe_price_id=price_id,
                        provider="simulated",
                        livemode=False,
                    )
                elif replacement.plan_version_id != version.id or replacement.livemode:
                    raise CommandError(
                        f"Identyfikator {price_id!r} jest przypisany do innej wersji planu."
                    )
                else:
                    replacement.stripe_product_id = product_id
                    replacement.is_active = True
                    replacement.save(
                        update_fields=["stripe_product_id", "is_active", "updated_at"]
                    )
                configured += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Simulated catalog ready: configured={configured}, unchanged={unchanged}."
            )
        )
