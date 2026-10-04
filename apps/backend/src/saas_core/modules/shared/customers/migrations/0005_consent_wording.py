from django.db import migrations, models


class Migration(migrations.Migration):
    """The consent journal keeps the sentence a person agreed to, not only its
    hash (ADR-073 §9): the evidence of a consent is the wording shown. Lines
    written before this have the hash alone and stay as they are — the column
    is added with an empty default, which rewrites no row and so does not
    meet the journal's append-only guard."""

    dependencies = [("customers", "0004_grant_role_permissions")]

    operations = [
        migrations.AddField(
            model_name="consentrecord",
            name="wording",
            field=models.TextField(blank=True, default=""),
        ),
    ]
