from django.db import migrations, models


class Migration(migrations.Migration):
    """Lets a collection entry own a media reference.

    The check constraint lists the owners the database will accept, so adding a
    kind in Python alone leaves every write failing at the last possible moment.
    """

    dependencies = [
        ("media", "0004_mediaasset_cleanup_completed_at_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="mediareference",
            name="media_ref_owner_type_ck",
        ),
        migrations.AddConstraint(
            model_name="mediareference",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    owner_type__in=[
                        "sites.page_version",
                        "sites.content_entry_version",
                        "sites.publication",
                    ]
                ),
                name="media_ref_owner_type_ck",
            ),
        ),
    ]
