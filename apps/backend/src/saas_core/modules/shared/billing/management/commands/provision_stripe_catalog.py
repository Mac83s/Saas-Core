"""Creates the Stripe Products and Prices our catalog describes.

Covers both halves of what we sell: the subscription plans (recurring) and the
credit packs (one-off). ADR-034 asks for active Product/Price pairs matching
the local catalog, separately for test and live. Doing that by hand in the
dashboard is where `tax_behavior` gets forgotten, and a price without it is
refused by `automatic_tax` at the first invoice — so it is a command, run the
same way in both modes, rather than a checklist.

Safe to repeat. A product carries a deterministic id derived from the catalog
key, and a price is reused when its amount, currency, interval and tax
behaviour already match; only a genuine change creates a new one and retires
the old.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saas_core.modules.shared.billing.models import (
    CreditPack,
    CreditPackPrice,
    Plan,
    PlanVersion,
    StripePriceMapping,
)

#: ADR-040: catalog amounts are net, so every price says so explicitly.
TAX_BEHAVIOR: Literal["exclusive"] = "exclusive"
BillingIntervalLiteral = Literal["day", "week", "month", "year"]


class Command(BaseCommand):
    help = "Tworzy w Stripe Produkty i Ceny dla planów oraz pakietów kredytów."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Pokaż, co zostałoby utworzone, bez wywołań zmieniających Stripe.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        if settings.BILLING_PROVIDER != "stripe":
            raise CommandError("Komenda wymaga BILLING_PROVIDER=stripe.")
        if not settings.STRIPE_SECRET_KEY:
            raise CommandError("Brak STRIPE_SECRET_KEY.")
        dry_run = bool(options["dry_run"])
        client = stripe.StripeClient(
            settings.STRIPE_SECRET_KEY,
            stripe_version=settings.STRIPE_API_VERSION,
            max_network_retries=2,
        )

        mode = "live" if settings.STRIPE_LIVEMODE else "test"
        self.stdout.write(f"Tryb Stripe: {mode}")
        offered: list[tuple[str, str]] = []
        for plan_key in settings.BILLING_PLAN_KEYS:
            plan = (
                Plan.objects.select_related("current_version")
                .filter(key=plan_key, is_active=True, current_version__isnull=False)
                .first()
            )
            if plan is None or plan.current_version is None:
                raise CommandError(f"Plan {plan_key!r} nie ma aktywnej bieżącej wersji.")
            if plan.current_version.unit_amount_minor == 0:
                # Nothing to sell: Stripe has no product for a free plan.
                continue
            pair = self._provision_plan(client, plan.current_version, dry_run=dry_run)
            if pair is not None:
                offered.append(pair)
        for pack in CreditPack.objects.filter(is_active=True).order_by("credits"):
            self._provision_pack(client, pack, dry_run=dry_run)
        if not dry_run:
            self._allow_switching_between(client, offered)

    def _allow_switching_between(
        self, client: stripe.StripeClient, offered: list[tuple[str, str]]
    ) -> None:
        """Lets the portal move a subscription between our own prices.

        ADR-032 routes plan changes through the portal until we have our own
        scheduler. The allowlist below is sent but must not be relied on:
        API version 2026-07-29.dahlia accepts `products` and returns it
        nowhere, so there is no way to confirm it applies. What actually keeps
        the portal to our catalog is that the deployment owns its Stripe
        account and `_ensure_price` deactivates every price that no longer
        matches — so the set of active prices is the catalog.
        """
        configuration_id = settings.STRIPE_PORTAL_CONFIGURATION_ID
        if not configuration_id:
            self.stdout.write("  portal: brak STRIPE_PORTAL_CONFIGURATION_ID, pomijam")
            return
        client.v1.billing_portal.configurations.update(
            configuration_id,
            {
                "features": {
                    "subscription_update": {
                        "enabled": True,
                        "default_allowed_updates": ["price"],
                        "proration_behavior": "create_prorations",
                        "products": [
                            {"product": product_id, "prices": [price_id]}
                            for product_id, price_id in offered
                        ],
                    }
                }
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  portal {configuration_id}: zmiana planu ograniczona do {len(offered)} cen"
            )
        )

    def _provision_plan(
        self,
        client: stripe.StripeClient,
        version: PlanVersion,
        *,
        dry_run: bool,
    ) -> tuple[str, str] | None:
        plan_key = version.plan.key
        product_id = f"saas_core_plan_{plan_key}"
        amount = version.unit_amount_minor
        currency = version.currency.lower()
        interval = version.billing_interval

        if dry_run:
            self.stdout.write(
                f"  [dry-run] {plan_key}: produkt {product_id}, "
                f"{amount / 100:.2f} {currency.upper()} / {interval}, netto"
            )
            return None

        product = self._ensure_product(
            client,
            product_id,
            name=version.plan.name,
            description=version.plan.description,
            metadata={
                "saas_core_plan": version.plan.key,
                "saas_core_plan_version": str(version.version),
            },
        )
        price = self._ensure_price(
            client,
            product_id=product.id,
            amount=amount,
            currency=currency,
            interval=interval,
        )
        created = self._map(version, product_id=product.id, price_id=price.id)
        self.stdout.write(
            self.style.SUCCESS(
                f"  {plan_key} v{version.version}: {price.id} "
                f"({amount / 100:.2f} {currency.upper()}/{interval}, netto) "
                f"— mapowanie {'utworzone' if created else 'bez zmian'}"
            )
        )
        return product.id, price.id

    def _provision_pack(
        self, client: stripe.StripeClient, pack: CreditPack, *, dry_run: bool
    ) -> None:
        """Credit packs are sold once, so their price has no recurring block."""
        product_id = f"saas_core_credits_{pack.key.replace('-', '_')}"
        currency = pack.currency.lower()
        if dry_run:
            self.stdout.write(
                f"  [dry-run] {pack.key}: produkt {product_id}, "
                f"{pack.unit_amount_minor / 100:.2f} {currency.upper()} jednorazowo, netto"
            )
            return

        product = self._ensure_product(
            client,
            product_id,
            name=pack.name,
            description=pack.description,
            metadata={
                "saas_core_credit_pack": pack.key,
                "saas_core_credits": str(pack.credits),
            },
        )
        price = self._ensure_price(
            client,
            product_id=product.id,
            amount=pack.unit_amount_minor,
            currency=currency,
            interval=None,
        )
        created = self._map_pack(pack, product_id=product.id, price_id=price.id)
        self.stdout.write(
            self.style.SUCCESS(
                f"  {pack.key}: {price.id} "
                f"({pack.unit_amount_minor / 100:.2f} {currency.upper()} jednorazowo, netto) "
                f"— mapowanie {'utworzone' if created else 'bez zmian'}"
            )
        )

    def _ensure_product(
        self,
        client: stripe.StripeClient,
        product_id: str,
        *,
        name: str,
        description: str,
        metadata: dict[str, str],
    ) -> Any:
        payload: Any = {
            "name": name,
            "tax_code": settings.STRIPE_TAX_CODE,
            "metadata": metadata,
        }
        if description:
            payload["description"] = description
        try:
            return client.v1.products.update(product_id, payload)
        except stripe.InvalidRequestError:
            # A deterministic id makes the command safe to repeat; Stripe only
            # accepts one at creation, which is why this is not an upsert.
            payload["id"] = product_id
            return client.v1.products.create(payload)

    def _ensure_price(
        self,
        client: stripe.StripeClient,
        *,
        product_id: str,
        amount: int,
        currency: str,
        interval: str | None,
    ) -> Any:
        for candidate in client.v1.prices.list({
            "product": product_id,
            "active": True,
            "limit": 100,
        }).data:
            recurring = getattr(candidate, "recurring", None)
            candidate_interval = (
                getattr(recurring, "interval", None) if recurring is not None else None
            )
            if (
                getattr(candidate, "unit_amount", None) == amount
                and getattr(candidate, "currency", None) == currency
                and getattr(candidate, "tax_behavior", None) == TAX_BEHAVIOR
                and candidate_interval == interval
            ):
                return candidate
            # A price is immutable in Stripe, so a changed amount means a new
            # one and the old must stop being offered.
            client.v1.prices.update(candidate.id, {"active": False})
        payload: Any = {
            "product": product_id,
            "currency": currency,
            "unit_amount": amount,
            "tax_behavior": TAX_BEHAVIOR,
        }
        if interval is not None:
            payload["recurring"] = {"interval": cast(BillingIntervalLiteral, interval)}
        return client.v1.prices.create(payload)

    def _map(self, version: PlanVersion, *, product_id: str, price_id: str) -> bool:
        with transaction.atomic():
            active = (
                StripePriceMapping.objects.select_for_update()
                .filter(
                    plan_version=version,
                    livemode=settings.STRIPE_LIVEMODE,
                    is_active=True,
                )
                .first()
            )
            if active is not None and active.stripe_price_id == price_id:
                return False
            if active is not None:
                active.is_active = False
                active.save(update_fields=["is_active", "updated_at"])
            existing = StripePriceMapping.objects.filter(stripe_price_id=price_id).first()
            if existing is not None:
                if existing.plan_version_id != version.id:
                    raise CommandError(f"Cena {price_id!r} jest przypisana do innej wersji planu.")
                existing.stripe_product_id = product_id
                existing.is_active = True
                existing.save(update_fields=["stripe_product_id", "is_active", "updated_at"])
                return True
            StripePriceMapping.objects.create(
                plan_version=version,
                stripe_product_id=product_id,
                stripe_price_id=price_id,
                provider="stripe",
                livemode=settings.STRIPE_LIVEMODE,
            )
            return True

    def _map_pack(self, pack: CreditPack, *, product_id: str, price_id: str) -> bool:
        with transaction.atomic():
            active = (
                CreditPackPrice.objects.select_for_update()
                .filter(pack=pack, livemode=settings.STRIPE_LIVEMODE, is_active=True)
                .first()
            )
            if active is not None and active.stripe_price_id == price_id:
                return False
            if active is not None:
                active.is_active = False
                active.save(update_fields=["is_active", "updated_at"])
            existing = CreditPackPrice.objects.filter(stripe_price_id=price_id).first()
            if existing is not None:
                if existing.pack_id != pack.id:
                    raise CommandError(f"Cena {price_id!r} jest przypisana do innego pakietu.")
                existing.stripe_product_id = product_id
                existing.is_active = True
                existing.save(update_fields=["stripe_product_id", "is_active", "updated_at"])
                return True
            CreditPackPrice.objects.create(
                pack=pack,
                stripe_product_id=product_id,
                stripe_price_id=price_id,
                livemode=settings.STRIPE_LIVEMODE,
            )
            return True
