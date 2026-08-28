from django.db import migrations, models


class Migration(migrations.Migration):
    """What a site and a page are for.

    Both columns are metadata: nothing in the rendering or publication path
    reads them, so existing rows take the neutral default and no site changes
    behaviour.
    """

    dependencies = [
        ("sites", "0013_entry_translation_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("customer", "Strona klienta"),
                    ("platform_marketing", "Strona marketingowa platformy"),
                    ("platform_blog", "Blog platformy"),
                ],
                default="customer",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="page",
            name="page_type",
            field=models.CharField(
                choices=[
                    ("homepage", "Strona główna"),
                    ("landing", "Landing"),
                    ("service", "Usługa"),
                    ("about", "O nas"),
                    ("contact", "Kontakt"),
                    ("legal", "Dokument prawny"),
                    ("article_index", "Indeks artykułów"),
                    ("article", "Artykuł"),
                ],
                default="landing",
                max_length=32,
            ),
        ),
    ]
