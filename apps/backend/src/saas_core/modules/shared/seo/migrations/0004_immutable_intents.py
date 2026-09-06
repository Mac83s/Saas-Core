from django.db import migrations

CREATE = """
CREATE FUNCTION seo_guard_durable_intent() RETURNS trigger AS $$
DECLARE
    immutable_fields text[];
    field_name text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.organization_id = NULLIF(current_setting('app.erasing_organization_id', true), '')::uuid THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'SEO history requires tenant erasure' USING ERRCODE = '55000';
    END IF;
    IF TG_TABLE_NAME = 'seo_auditcallbackreceipt' THEN
        RAISE EXCEPTION 'SEO callback receipt is immutable' USING ERRCODE = '55000';
    ELSIF TG_TABLE_NAME = 'seo_sourcesitebinding' THEN
        immutable_fields := ARRAY['id','organization_id','site_id','source_id','external_project_id','name','root_url'];
    ELSE
        IF OLD.state IN ('completed','partial','failed','cancelled') THEN
            RAISE EXCEPTION 'SEO terminal order is immutable' USING ERRCODE = '55000';
        END IF;
        immutable_fields := ARRAY['id','organization_id','binding_id','created_by_id','membership_id',
            'idempotency_key','request_hash','requested_options','credit_operation_key',
            'credit_reservation_key','credit_cost','created_at'];
    END IF;
    FOREACH field_name IN ARRAY immutable_fields LOOP
        IF to_jsonb(OLD)->field_name IS DISTINCT FROM to_jsonb(NEW)->field_name THEN
            RAISE EXCEPTION 'SEO intent field % is immutable', field_name USING ERRCODE = '55000';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER seo_binding_intent BEFORE UPDATE OR DELETE ON seo_sourcesitebinding
FOR EACH ROW EXECUTE FUNCTION seo_guard_durable_intent();
CREATE TRIGGER seo_order_intent BEFORE UPDATE OR DELETE ON seo_auditorder
FOR EACH ROW EXECUTE FUNCTION seo_guard_durable_intent();
CREATE TRIGGER seo_callback_intent BEFORE UPDATE OR DELETE ON seo_auditcallbackreceipt
FOR EACH ROW EXECUTE FUNCTION seo_guard_durable_intent();
"""
DROP = """
DROP TRIGGER seo_callback_intent ON seo_auditcallbackreceipt;
DROP TRIGGER seo_order_intent ON seo_auditorder;
DROP TRIGGER seo_binding_intent ON seo_sourcesitebinding;
DROP FUNCTION seo_guard_durable_intent();
"""


class Migration(migrations.Migration):
    dependencies = [("seo", "0003_feature_catalog")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
