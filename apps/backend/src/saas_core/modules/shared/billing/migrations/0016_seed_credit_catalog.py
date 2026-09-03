from typing import Any

from django.db import migrations

# The monthly allowance is an ordinary entitlement quota, so it is versioned
# with the plan, overridable per organization and already visible in the
# entitlement snapshot. Credits do not get a second catalog for it.
ALLOWANCE_QUOTA = {
    "key": "credits.monthly",
    "name": "Kredyty w planie (miesięcznie)",
    "unit": "count",
    "period": "month",
    "description": "Pula kredytów odnawiana co miesiąc; nie przechodzi na kolejny okres.",
}

# What each plan is meant to include. These figures are NOT written into the
# seeded plan versions here: a published version is immutable in the model and
# in the database (trigger billing_plan_version_immutable, migration 0003), so
# changing what a plan grants means publishing a new version. The pilot catalog
# gets its new versions with W9.5.2S, when real Stripe Product/Price ids force
# a version bump anyway — doing it twice would leave two catalogs to migrate.
#
# Until then the allowance is zero for the seeded plans and only purchased
# credits move. Nothing else waits on it: the mechanism reads the allowance
# from the entitlement snapshot, so a plan version that declares
# `credits.monthly` starts granting it the moment it is current, and an
# operator override can grant it to one organization today.
PLAN_ALLOWANCES = {"profile": 50, "starter": 200, "pro": 1000}

CREDIT_PACKS = (
    {
        "key": "credits-100",
        "name": "100 kredytów",
        "description": "Mały pakiet na doraźne potrzeby.",
        "credits": 100,
        "unit_amount_minor": 4_900,
    },
    {
        "key": "credits-500",
        "name": "500 kredytów",
        "description": "Pakiet na regularną pracę z asystentem.",
        "credits": 500,
        "unit_amount_minor": 19_900,
    },
    {
        "key": "credits-2000",
        "name": "2000 kredytów",
        "description": "Pakiet dla intensywnej produkcji treści.",
        "credits": 2_000,
        "unit_amount_minor": 69_900,
    },
)

# `is_active` means metered. An operation seeded inactive costs nothing until
# somebody turns it on, so switching a surface to paid is a catalog decision
# rather than a deployment. Content operations start inactive on purpose:
# SeoContentRank refuses fail-closed on an answer it does not understand, so
# charging its commands has to be agreed on both sides first (W9.6).
CREDIT_OPERATIONS = (
    {
        "key": "assistant.generate_draft",
        "name": "Wygenerowanie szkicu strony",
        "description": "Brief lub rozmowa zamieniona na szkic strony z zatwierdzonego szablonu.",
        "cost": 10,
        "is_active": True,
    },
    {
        "key": "assistant.rewrite_block",
        "name": "Przepisanie bloku treści",
        "description": "Zmiana tekstu pojedynczej sekcji strony.",
        "cost": 2,
        "is_active": True,
    },
    {
        "key": "assistant.compose_message",
        "name": "Przygotowanie wiadomości",
        "description": "Wiadomość do klienta przygotowana przez asystenta.",
        "cost": 2,
        "is_active": True,
    },
    {
        "key": "assistant.conversation_turn",
        "name": "Tura rozmowy z asystentem",
        "description": "Jedno pytanie i odpowiedź w panelu.",
        "cost": 1,
        "is_active": True,
    },
    {
        "key": "content_operations.proposal",
        "name": "Propozycja zmiany treści",
        "description": "Change set przyjęty od zewnętrznej automatyzacji.",
        "cost": 1,
        "is_active": False,
    },
    {
        "key": "content_operations.publication",
        "name": "Publikacja z automatyzacji",
        "description": "Publikacja wykonana przez zewnętrzną automatyzację.",
        "cost": 2,
        "is_active": False,
    },
)


def seed_credit_catalog(apps: Any, schema_editor: Any) -> None:
    quota_model = apps.get_model("billing", "QuotaDefinition")
    pack_model = apps.get_model("billing", "CreditPack")
    operation_model = apps.get_model("billing", "CreditOperation")

    quota_model.objects.update_or_create(
        key=ALLOWANCE_QUOTA["key"],
        defaults={
            "name": ALLOWANCE_QUOTA["name"],
            "unit": ALLOWANCE_QUOTA["unit"],
            "period": ALLOWANCE_QUOTA["period"],
            "description": ALLOWANCE_QUOTA["description"],
            "is_active": True,
        },
    )

    for pack in CREDIT_PACKS:
        pack_model.objects.update_or_create(
            key=pack["key"],
            defaults={
                "name": pack["name"],
                "description": pack["description"],
                "credits": pack["credits"],
                "currency": "PLN",
                "unit_amount_minor": pack["unit_amount_minor"],
                "is_public": True,
                "is_active": True,
            },
        )

    for operation in CREDIT_OPERATIONS:
        operation_model.objects.update_or_create(
            key=operation["key"],
            defaults={
                "name": operation["name"],
                "description": operation["description"],
                "cost": operation["cost"],
                "is_active": operation["is_active"],
            },
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0015_credit_rls_and_guards")]

    operations = [migrations.RunPython(seed_credit_catalog, migrations.RunPython.noop)]
