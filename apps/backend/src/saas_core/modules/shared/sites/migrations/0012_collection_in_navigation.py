from django.db import migrations, models


class Migration(migrations.Migration):
    """Lets the published menu link to a collection.

    A flag rather than a navigation row: the menu points at pages, and teaching
    it a second kind of target costs a nullable foreign key, a check constraint
    and a parent key spanning two id spaces. A blog sits at the end of a menu,
    which is what this buys.
    """

    dependencies = [
        ("sites", "0011_content_proposal_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentcollection",
            name="show_in_navigation",
            field=models.BooleanField(default=False),
        ),
    ]
