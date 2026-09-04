from django.db import migrations, models

# The simulator generates its own identifiers, so its rows can be stamped
# exactly rather than guessed. Everything else came from Stripe, which is what
# the column already defaults to.
STAMP_SIMULATED = """
UPDATE billing_stripepricemapping
SET provider = 'simulated'
WHERE stripe_price_id LIKE 'sim\\_price\\_%'
"""

UNSTAMP = """
UPDATE billing_stripepricemapping
SET provider = 'stripe'
WHERE provider = 'simulated'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0020_activation_per_checkout"),
    ]

    operations = [
        migrations.AddField(
            model_name="stripepricemapping",
            name="provider",
            field=models.CharField(default="stripe", max_length=16),
        ),
        migrations.RunSQL(STAMP_SIMULATED, UNSTAMP),
    ]
