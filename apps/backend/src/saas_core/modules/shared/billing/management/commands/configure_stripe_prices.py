from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from saas_core.modules.shared.billing.models import Plan, PlanVersion, StripePriceMapping
from saas_core.modules.shared.billing.provider import (
    BillingProvider,
    BillingProviderError,
    ProviderPrice,
    get_billing_provider,
)


@dataclass(frozen=True, slots=True)
class RequestedMapping:
    plan_key: str
    product_id: str
    price_id: str


class Command(BaseCommand):
    help = "Configure or verify active Stripe Price mappings for the public catalog."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--mapping",
            action="append",
            default=[],
            metavar="PLAN=PRODUCT_ID,PRICE_ID",
            help="Repeat for each mapping, for example profile=prod_123,price_123.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--livemode",
            dest="livemode",
            action="store_true",
            default=None,
            help="Configure/check live mappings instead of Stripe test mode.",
        )
        mode.add_argument(
            "--testmode",
            dest="livemode",
            action="store_false",
            help="Explicitly configure/check Stripe test mappings.",
        )
        parser.set_defaults(livemode=None)
        parser.add_argument(
            "--check",
            action="store_true",
            help="Verify every public current plan and its remote Stripe Price.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        requested = [_parse_mapping(value) for value in options["mapping"]]
        livemode_option = options["livemode"]
        livemode = settings.STRIPE_LIVEMODE if livemode_option is None else bool(livemode_option)
        if not requested and not options["check"]:
            raise CommandError("Podaj co najmniej jedno --mapping albo użyj --check.")
        duplicate_keys = _duplicates(item.plan_key for item in requested)
        if duplicate_keys:
            raise CommandError("Plan podano więcej niż raz: " + ", ".join(sorted(duplicate_keys)))

        with transaction.atomic():
            for item in requested:
                changed = configure_mapping(item, livemode=livemode)
                state = "configured" if changed else "unchanged"
                self.stdout.write(f"{item.plan_key}: {state}")
            if options["check"]:
                validate_public_catalog(livemode=livemode)

        if options["check"]:
            mode = "live" if livemode else "test"
            self.stdout.write(self.style.SUCCESS(f"Stripe catalog is complete ({mode})."))


def _parse_mapping(value: str) -> RequestedMapping:
    try:
        plan_key, identifiers = value.strip().split("=", 1)
        product_id, price_id = identifiers.split(",", 1)
    except ValueError as error:
        raise CommandError("Mapping musi mieć format PLAN=PRODUCT_ID,PRICE_ID.") from error
    plan_key = plan_key.strip().lower()
    product_id = product_id.strip()
    price_id = price_id.strip()
    if not plan_key or not product_id.startswith("prod_") or not price_id.startswith("price_"):
        raise CommandError("Mapping wymaga klucza planu oraz identyfikatorów prod_* i price_*.")
    if len(product_id) > 160 or len(price_id) > 160:
        raise CommandError("Identyfikator Stripe przekracza 160 znaków.")
    return RequestedMapping(plan_key, product_id, price_id)


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def configure_mapping(requested: RequestedMapping, *, livemode: bool) -> bool:
    plan = (
        Plan.objects.select_for_update()
        .filter(
            key=requested.plan_key,
            key__in=settings.BILLING_PLAN_KEYS,
            is_active=True,
            is_public=True,
            current_version__isnull=False,
        )
        .first()
    )
    if plan is None or plan.current_version is None:
        raise CommandError(f"Plan {requested.plan_key!r} nie jest aktywnym planem publicznym.")
    version: PlanVersion = plan.current_version
    conflicting = StripePriceMapping.objects.filter(stripe_price_id=requested.price_id).exclude(
        plan_version=version,
        livemode=livemode,
    )
    if conflicting.exists():
        raise CommandError(
            f"Stripe Price {requested.price_id!r} jest już przypisany do innej wersji."
        )
    active = (
        StripePriceMapping.objects.select_for_update()
        .filter(plan_version=version, livemode=livemode, is_active=True)
        .first()
    )
    if (
        active is not None
        and active.stripe_product_id == requested.product_id
        and active.stripe_price_id == requested.price_id
    ):
        return False
    if active is not None:
        active.is_active = False
        active.save(update_fields=["is_active", "updated_at"])

    replacement = StripePriceMapping.objects.filter(
        plan_version=version,
        livemode=livemode,
        stripe_price_id=requested.price_id,
    ).first()
    if replacement is None:
        StripePriceMapping.objects.create(
            plan_version=version,
            stripe_product_id=requested.product_id,
            stripe_price_id=requested.price_id,
            livemode=livemode,
        )
    else:
        replacement.stripe_product_id = requested.product_id
        replacement.is_active = True
        replacement.save(update_fields=["stripe_product_id", "is_active", "updated_at"])
    return True


def validate_public_catalog(
    *,
    livemode: bool,
    provider: BillingProvider | None = None,
) -> None:
    plans = list(
        Plan.objects.filter(
            key__in=settings.BILLING_PLAN_KEYS,
            is_active=True,
            is_public=True,
            current_version__isnull=False,
        ).select_related("current_version")
    )
    current_versions = [plan.current_version for plan in plans if plan.current_version is not None]
    mappings = {
        mapping.plan_version.id: mapping
        for mapping in StripePriceMapping.objects.select_related("plan_version").filter(
            plan_version__in=current_versions,
            livemode=livemode,
            is_active=True,
        )
    }
    missing = [
        plan.key
        for plan in plans
        if plan.current_version is None or plan.current_version.id not in mappings
    ]
    if missing:
        mode = "live" if livemode else "test"
        raise CommandError(
            f"Brak aktywnego Stripe Price ({mode}) dla planów: {', '.join(sorted(missing))}."
        )
    if not plans:
        return

    try:
        selected_provider = provider or get_billing_provider()
    except ImproperlyConfigured as error:
        raise CommandError("Nie można zweryfikować katalogu Stripe.") from error

    errors: list[str] = []
    for plan in plans:
        version = plan.current_version
        if version is None:  # Query excludes this; keep the runtime contract explicit.
            continue
        mapping = mappings[version.id]
        try:
            provider_price = selected_provider.retrieve_price(mapping.stripe_price_id)
        except BillingProviderError as error:
            errors.append(f"{plan.key}: {error}")
            continue
        errors.extend(_price_errors(plan.key, version, mapping, provider_price, livemode))
    if errors:
        raise CommandError("Nieprawidłowy katalog Stripe: " + "; ".join(errors) + ".")


def _price_errors(
    plan_key: str,
    version: PlanVersion,
    mapping: StripePriceMapping,
    price: ProviderPrice,
    livemode: bool,
) -> list[str]:
    errors: list[str] = []
    if price.id != mapping.stripe_price_id:
        errors.append(f"{plan_key}: Stripe zwrócił inny Price ID")
    if not price.active:
        errors.append(f"{plan_key}: Stripe Price jest nieaktywny")
    if price.livemode != livemode:
        errors.append(f"{plan_key}: tryb live/test Stripe Price jest niezgodny")
    if price.product_id != mapping.stripe_product_id:
        errors.append(f"{plan_key}: Stripe Price należy do innego Product")
    if price.unit_amount_minor != version.unit_amount_minor:
        errors.append(f"{plan_key}: kwota Stripe Price jest niezgodna")
    if price.currency.upper() != version.currency:
        errors.append(f"{plan_key}: waluta Stripe Price jest niezgodna")
    if price.recurring_interval != version.billing_interval:
        errors.append(f"{plan_key}: interwał Stripe Price jest niezgodny")
    if price.recurring_interval_count != 1:
        errors.append(f"{plan_key}: Stripe Price musi rozliczać każdy pojedynczy okres")
    return errors
