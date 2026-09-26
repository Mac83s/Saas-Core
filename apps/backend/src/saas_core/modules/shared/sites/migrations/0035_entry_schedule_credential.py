from django.db import migrations, models


class Migration(migrations.Migration):
    """An integration's scheduled publication names the key that scheduled it.

    A key has no membership, so the synthetic one stored until now could never
    be asked again when the moment came, and the publication never ran. A
    pending schedule now carries exactly one authority: a membership or a
    credential. Existing pending rows keep their membership and still satisfy
    the constraint; reversing drops the column and restores the old one.
    """

    dependencies = [("sites", "0034_aibadgeswitch")]

    operations = [
        migrations.RemoveConstraint(
            model_name="contententry",
            name="sites_entry_pending_schedule_complete_ck",
        ),
        migrations.AddField(
            model_name="contententry",
            name="scheduled_credential_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="contententry",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(schedule_state="pending")
                    | (
                        models.Q(scheduled_publish_at__isnull=False)
                        & (
                            models.Q(
                                scheduled_membership_id__isnull=False,
                                scheduled_credential_id__isnull=True,
                            )
                            | models.Q(
                                scheduled_membership_id__isnull=True,
                                scheduled_credential_id__isnull=False,
                            )
                        )
                    )
                ),
                name="sites_entry_pending_schedule_complete_ck",
            ),
        ),
    ]
