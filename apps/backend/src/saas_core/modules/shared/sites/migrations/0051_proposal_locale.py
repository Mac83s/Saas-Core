from typing import Any

from django.conf import settings
from django.db import migrations, models

# ADR-070 pkt 17: a page has one change-set base per language, so a proposal
# names its language and the uniqueness key carries it — a German and a Polish
# proposal for one page may hold the same version number. Existing rows take
# the language their change set named; a row that names none (none is written
# by the application) takes its page's source language or its entry's own.
# Runs as the table owner, so FORCE RLS does not hide other tenants' rows.
BACKFILL = """
UPDATE sites_contentproposal p
SET locale = COALESCE(
    substring(p.target->>'locale' from '^[a-z]{2}'),
    (
        SELECT s.default_locale FROM sites_page g
        JOIN sites_site s ON s.id = g.site_id
        WHERE g.id = p.resource_id AND p.resource_type = 'site_page'
    ),
    (
        SELECT e.locale FROM sites_contententry e
        WHERE e.id = p.resource_id AND p.resource_type = 'content_entry'
    ),
    %s
)
WHERE p.locale = ''
"""


def name_the_language(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(BACKFILL, [settings.SITES_DEFAULT_LOCALE])


def refuse_walking_back_over_language_proposals(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM ("
            "SELECT 1 FROM sites_contentproposal "
            "GROUP BY organization_id, resource_type, resource_id, version "
            "HAVING count(*) > 1) repeated"
        )
        (repeated,) = cursor.fetchone()
    if repeated:
        raise RuntimeError(
            "Cofnięcie sites 0051 przywraca jedną propozycję na wersję zasobu, a "
            f"{repeated} wersji ma propozycje w kilku językach. Usuń je albo zmień "
            "świadomie, potem cofnij ponownie."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0050_inquiry_erased_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentproposal",
            name="locale",
            field=models.CharField(default="", max_length=10),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="contentproposal",
            name="locale_version_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(name_the_language, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="contentproposal",
            name="sites_proposal_org_resource_version_uq",
        ),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_walking_back_over_language_proposals
        ),
        migrations.AddConstraint(
            model_name="contentproposal",
            constraint=models.UniqueConstraint(
                fields=("organization", "resource_type", "resource_id", "locale", "version"),
                name="sites_proposal_org_resource_locale_version_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="contentproposal",
            constraint=models.CheckConstraint(
                condition=models.Q(("locale__regex", "^[a-z]{2}$")),
                name="sites_proposal_locale_format_ck",
            ),
        ),
    ]
