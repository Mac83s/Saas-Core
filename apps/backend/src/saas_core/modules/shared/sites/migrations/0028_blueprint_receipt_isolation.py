from typing import Any

from django.db import migrations

CREATE = """
ALTER TABLE sites_blueprintimportreceipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites_blueprintimportreceipt FORCE ROW LEVEL SECURITY;
CREATE POLICY sites_blueprint_receipt_tenant ON sites_blueprintimportreceipt
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid);
CREATE FUNCTION sites_guard_blueprint_receipt() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.organization_id = NULLIF(current_setting('app.erasing_organization_id', true), '')::uuid THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Blueprint receipt requires tenant erasure' USING ERRCODE = '55000';
    ELSIF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Blueprint receipt is immutable' USING ERRCODE = '55000';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM sites_page p
        JOIN sites_site s ON s.id = p.site_id
        JOIN sites_contentproposal r ON r.id = NEW.proposal_id
        WHERE p.id = NEW.page_id AND s.id = NEW.site_id
        AND s.organization_id = NEW.organization_id AND p.organization_id = NEW.organization_id
        AND r.organization_id = NEW.organization_id AND r.resource_type = 'site_page'
        AND r.resource_id = p.id
    ) THEN
        RAISE EXCEPTION 'Blueprint receipt relation mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER sites_blueprint_receipt_guard BEFORE INSERT OR UPDATE OR DELETE
ON sites_blueprintimportreceipt FOR EACH ROW EXECUTE FUNCTION sites_guard_blueprint_receipt();
"""
DROP = """
DROP TRIGGER sites_blueprint_receipt_guard ON sites_blueprintimportreceipt;
DROP FUNCTION sites_guard_blueprint_receipt();
DROP POLICY sites_blueprint_receipt_tenant ON sites_blueprintimportreceipt;
ALTER TABLE sites_blueprintimportreceipt NO FORCE ROW LEVEL SECURITY;
ALTER TABLE sites_blueprintimportreceipt DISABLE ROW LEVEL SECURITY;
"""


def preserve_receipts(apps: Any, schema_editor: Any) -> None:
    receipt = apps.get_model("sites", "BlueprintImportReceipt")
    if receipt.all_objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError(
            "Blueprint receipts exist; retain this schema during application rollback."
        )


class Migration(migrations.Migration):
    dependencies = [("sites", "0027_blueprint_import_receipt")]
    operations = [
        migrations.RunSQL(CREATE, reverse_sql=DROP),
        migrations.RunPython(migrations.RunPython.noop, preserve_receipts),
    ]
