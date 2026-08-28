import uuid
from typing import Any

from django.db import migrations, models


def assign_groups(apps: Any, schema_editor: Any) -> None:
    """Every existing entry becomes its own group of one.

    Django computes a callable default once and writes that single value to
    every existing row, which would declare all of a customer's articles
    translations of each other — and then fail the unique constraint the moment
    two of them share a language. Each row gets its own id here instead.
    """
    # One statement rather than a loop: the historical model has no manager
    # named `objects` (the real one is tenant-scoped), and a per-row UPDATE
    # would be a query per article for no benefit.
    schema_editor.execute(
        "UPDATE sites_contententry SET translation_group = gen_random_uuid()"
    )


class Migration(migrations.Migration):
    """Groups the language versions of one article."""

    dependencies = [
        ("sites", "0012_collection_in_navigation"),
    ]

    operations = [
        migrations.AddField(
            model_name="contententry",
            name="translation_group",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_groups, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="contententry",
            name="translation_group",
            field=models.UUIDField(default=uuid.uuid7, editable=False),
        ),
        migrations.AddConstraint(
            model_name="contententry",
            constraint=models.UniqueConstraint(
                fields=("organization", "translation_group", "locale"),
                name="sites_entry_org_group_locale_uq",
            ),
        ),
        migrations.AddIndex(
            model_name="contententry",
            index=models.Index(
                fields=["organization", "translation_group"],
                name="sites_entry_group_idx",
            ),
        ),
    ]
