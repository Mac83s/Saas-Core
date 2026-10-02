from typing import Any

from django.db import migrations

# ADR-071 pkt 4: an existing company's languages are its own, then the
# languages its profiles already have. Runs as the table owner, so FORCE RLS does
# not hide other tenants' rows; the publisher already has every language.
SQL = """
UPDATE organizations_organization o
SET public_locales = o.public_locales || ARRAY(
    SELECT DISTINCT found.code FROM (
        SELECT p.locale AS code FROM profiles_publicprofile p WHERE p.organization_id = o.id
        UNION SELECT t.locale FROM profiles_publicprofiletranslation t WHERE t.organization_id = o.id
    ) found
    WHERE found.code ~ '^[a-z]{2}$' AND NOT found.code = ANY(o.public_locales)
    ORDER BY found.code
)::varchar(10)[]
WHERE o.workspace_kind <> 'platform'
"""


def append_locales(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0004_publish_profiles_feature"),
        ("organizations", "0053_organization_public_locales"),
    ]

    operations = [migrations.RunPython(append_locales, migrations.RunPython.noop)]
