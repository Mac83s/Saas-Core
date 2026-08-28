from django.db import migrations

# The cross-tenant guard predates entry publications, so it dereferenced
# `publication_id` unconditionally. With the column now nullable that check
# refuses every entry event: the row is correct and the trigger says otherwise.
# Each subject is checked only when it is the one that is set.
UPDATE_OUTBOX_GUARD = """
CREATE OR REPLACE FUNCTION sites_validate_outbox_event()
RETURNS trigger AS $$
BEGIN
    IF NEW.publication_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM sites_publication
        WHERE id = NEW.publication_id
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'outbox publication belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.entry_publication_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM sites_contententrypublication
        WHERE id = NEW.entry_publication_id
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'outbox entry publication belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.publication_id IS DISTINCT FROM OLD.publication_id
        OR NEW.entry_publication_id IS DISTINCT FROM OLD.entry_publication_id
        OR NEW.event_type IS DISTINCT FROM OLD.event_type
        OR NEW.version IS DISTINCT FROM OLD.version
        OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
        OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
        OR NEW.causation_id IS DISTINCT FROM OLD.causation_id
        OR NEW.payload IS DISTINCT FROM OLD.payload
        OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
        OR (OLD.published_at IS NOT NULL AND NEW.published_at IS DISTINCT FROM OLD.published_at)
    ) THEN
        RAISE EXCEPTION 'outbox event payload is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

RESTORE_OUTBOX_GUARD = """
CREATE OR REPLACE FUNCTION sites_validate_outbox_event()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sites_publication
        WHERE id = NEW.publication_id
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'outbox publication belongs to another organization'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.id IS DISTINCT FROM OLD.id
        OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
        OR NEW.publication_id IS DISTINCT FROM OLD.publication_id
        OR NEW.event_type IS DISTINCT FROM OLD.event_type
        OR NEW.version IS DISTINCT FROM OLD.version
        OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
        OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
        OR NEW.causation_id IS DISTINCT FROM OLD.causation_id
        OR NEW.payload IS DISTINCT FROM OLD.payload
        OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
        OR (OLD.published_at IS NOT NULL AND NEW.published_at IS DISTINCT FROM OLD.published_at)
    ) THEN
        RAISE EXCEPTION 'outbox event payload is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("sites", "0016_entry_publication_schedule")]

    operations = [
        migrations.RunSQL(UPDATE_OUTBOX_GUARD, RESTORE_OUTBOX_GUARD),
    ]
