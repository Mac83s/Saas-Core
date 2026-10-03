"""The card's languages onto the catalogue rows that exist (TL20).

Not atomic on purpose: one short transaction per entry, each naming its tenant
before it reads the card, so a large catalogue neither holds one long
transaction nor locks the table it is filling. A run cut short is finished by
running it again — every row is recomputed from its card.
"""

import hashlib
from typing import Any

from django.conf import settings
from django.db import migrations, transaction

#: Entries per pass: one tenant at a time inside, so a large catalogue never
#: holds one long transaction.
BATCH = 500


def _link_key(url: str) -> str:
    # `translation_source.link_key` as of TL12a, copied so the backfill does not
    # change when the module does.
    return "link/" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _complete(profile: Any, row: Any) -> bool:
    """Every text of the card translated, none of it the source's copy (TL20).
    Mirrors `card_languages.card_in_language` returning no fallback."""
    copied = {
        key
        for key, origin in (row.provenance or {}).items()
        if isinstance(origin, dict) and origin.get("origin") == "copy"
    }
    if profile.headline and ("headline" in copied or not row.headline):
        return False
    if profile.bio and ("bio" in copied or not row.bio):
        return False
    labels = {key for key in (row.link_labels or {}) if key not in copied}
    return all(_link_key(link["url"]) in labels for link in profile.links or ())


def fill_languages(apps: Any, schema_editor: Any) -> None:
    """The card's languages onto every catalogue row. Idempotent: a row is
    recomputed from the card each time, so a second run writes the same."""
    # `_base_manager`: the tenant managers are not part of a migration's state.
    entries = apps.get_model("profiles", "CatalogEntry")
    profiles = apps.get_model("profiles", "PublicProfile")
    translations = apps.get_model("profiles", "PublicProfileTranslation")
    organizations = apps.get_model("organizations", "Organization")
    supported = set(settings.SITES_SUPPORTED_LOCALES)
    connection = schema_editor.connection
    last = None
    while True:
        batch = entries._base_manager.order_by("id")
        if last is not None:
            batch = batch.filter(id__gt=last)
        rows = list(batch.values_list("id", "organization_id", "profile_id")[:BATCH])
        if not rows:
            return
        last = rows[-1][0]
        for entry_id, organization_id, profile_id in rows:
            with transaction.atomic(using=connection.alias):
                # The card and its translations force RLS: name the tenant first.
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL app.organization_id = %s", [str(organization_id)])
                profile = profiles._base_manager.filter(
                    pk=profile_id, organization_id=organization_id
                ).first()
                organization = organizations._base_manager.filter(pk=organization_id).first()
                if profile is None or organization is None:
                    continue
                offered = [code for code in organization.public_locales if code in supported]
                headlines = {
                    row.locale: row.headline
                    for row in translations._base_manager.filter(
                        organization_id=organization_id, profile_id=profile_id, locale__in=offered
                    ).exclude(locale=profile.locale)
                    if _complete(profile, row)
                }
                ordered = [code for code in offered if code in headlines]
                entries._base_manager.filter(pk=entry_id).update(
                    source_locale=profile.locale,
                    translated_locales=ordered,
                    headline_by_locale={code: headlines[code] for code in ordered},
                )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("organizations", "0053_organization_public_locales"),
        ("profiles", "0009_catalog_entry_languages"),
    ]

    # Reverse: nothing to undo; the columns go with 0009's fields.
    operations = [migrations.RunPython(fill_languages, migrations.RunPython.noop)]
