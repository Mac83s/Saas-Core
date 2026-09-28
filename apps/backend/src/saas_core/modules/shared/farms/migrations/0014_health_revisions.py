import django.db.models.deletion
from django.db import migrations, models

#: An entry in an animal's history is never rewritten nor deleted once written
#: (decision of 28.09): a correction is the next revision of the same (source,
#: reference) and the one it replaces stays, marked retracted.

#: The guard of 0008 plus the correction's own relation: an entry corrects an
#: entry of the same animal, in the same organization.
GUARD_WITH_CORRECTS = """
CREATE OR REPLACE FUNCTION farms_validate_health_relations()
RETURNS trigger AS $$
DECLARE
    relation_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM farms_animal
        WHERE id = NEW.animal_id AND organization_id = NEW.organization_id
    ) INTO relation_ok;
    IF NOT relation_ok THEN
        RAISE EXCEPTION 'farms relation belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.corrects_id IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM farms_animalhealthentry
            WHERE id = NEW.corrects_id
              AND organization_id = NEW.organization_id
              AND animal_id = NEW.animal_id
        ) INTO relation_ok;
        IF NOT relation_ok THEN
            RAISE EXCEPTION 'farms relation belongs to another organization'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

#: The body of 0008, for the way back.
GUARD_WITHOUT_CORRECTS = """
CREATE OR REPLACE FUNCTION farms_validate_health_relations()
RETURNS trigger AS $$
DECLARE
    relation_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM farms_animal
        WHERE id = NEW.animal_id AND organization_id = NEW.organization_id
    ) INTO relation_ok;
    IF NOT relation_ok THEN
        RAISE EXCEPTION 'farms relation belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

#: After the insert only the retraction may be set, once; deleting is the
#: erasure's alone (`app.erasing_organization_id`, the pattern of hoofcare 0010).
APPEND_ONLY = """
CREATE OR REPLACE FUNCTION farms_health_append_only()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.organization_id = NULLIF(
            current_setting('app.erasing_organization_id', true), ''
        )::uuid THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'farms health entries are append-only'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.retracted_at IS NULL AND NEW.retracted_at IS NOT NULL
       AND (to_jsonb(NEW) - 'retracted_at' - 'published_at')
           = (to_jsonb(OLD) - 'retracted_at' - 'published_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'farms health entries are append-only'
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER farms_animalhealthentry_append_only
    BEFORE UPDATE OR DELETE ON farms_animalhealthentry
    FOR EACH ROW EXECUTE FUNCTION farms_health_append_only();
"""
DROP_APPEND_ONLY = """
DROP TRIGGER IF EXISTS farms_animalhealthentry_append_only ON farms_animalhealthentry;
DROP FUNCTION IF EXISTS farms_health_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("farms", "0013_health_withdrawal")]

    operations = [
        migrations.AddField(
            model_name="animalhealthentry",
            name="revision",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="animalhealthentry",
            name="corrects",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="corrections",
                to="farms.animalhealthentry",
            ),
        ),
        migrations.AddField(
            model_name="animalhealthentry",
            name="correction_reason",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name="animalhealthentry",
            name="corrected_by",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="animalhealthentry",
            name="retracted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="animalhealthentry",
            name="farms_health_source_uq",
        ),
        migrations.AddConstraint(
            model_name="animalhealthentry",
            constraint=models.UniqueConstraint(
                fields=("organization", "animal", "source", "source_reference", "revision"),
                name="farms_health_revision_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="animalhealthentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(retracted_at__isnull=True),
                fields=("organization", "animal", "source", "source_reference"),
                name="farms_health_current_uq",
            ),
        ),
        migrations.RunSQL(GUARD_WITH_CORRECTS, reverse_sql=GUARD_WITHOUT_CORRECTS),
        migrations.RunSQL(APPEND_ONLY, reverse_sql=DROP_APPEND_ONLY),
    ]
