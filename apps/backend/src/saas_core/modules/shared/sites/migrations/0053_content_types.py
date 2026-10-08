"""A section becomes a content type (ADR-079 pkt 1): three fields, schema only.

Each defaults to what every section was before the field: switched on
(`archived_at` empty), a blog to search engines (`schema_type`), in the site's
feeds (`in_site_feed`). No row is rewritten and no constraint changes, so the
shape of a deployment's data does not matter to this migration, and its
reverse only drops the columns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0052_collection_locale_paths"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentcollection",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contentcollection",
            name="in_site_feed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="contentcollection",
            name="schema_type",
            field=models.CharField(
                choices=[
                    ("BlogPosting", "Wpis bloga"),
                    ("NewsArticle", "Aktualność"),
                    ("Article", "Artykuł"),
                    ("WebPage", "Strona"),
                ],
                default="BlogPosting",
                max_length=16,
            ),
        ),
    ]
