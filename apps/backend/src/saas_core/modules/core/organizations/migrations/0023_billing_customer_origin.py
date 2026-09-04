from django.db import migrations, models

# Every id the simulator ever handed out carries its own prefix, so those can
# be stamped exactly. A cus_… is left unstamped on purpose: it was issued by
# Stripe in whichever mode this deployment was running, and guessing wrong
# would make Billing create a second customer for a company that already has
# one. Unstamped means "assume it belongs here", which is how it behaved
# before this column existed.
STAMP_SIMULATED = """
UPDATE organizations_billingprofile
SET external_customer_provider = 'simulated'
WHERE external_customer_id LIKE 'sim\\_customer\\_%'
"""

UNSTAMP = """
UPDATE organizations_billingprofile
SET external_customer_provider = ''
WHERE external_customer_provider = 'simulated'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0022_credits"),
    ]

    operations = [
        migrations.AddField(
            model_name="billingprofile",
            name="external_customer_livemode",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="billingprofile",
            name="external_customer_provider",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.RunSQL(STAMP_SIMULATED, UNSTAMP),
    ]
