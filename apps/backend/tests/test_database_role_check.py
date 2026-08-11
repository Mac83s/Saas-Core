from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from saas_core.modules.core.organizations.management.commands import check_database_role
from saas_core.modules.core.organizations.management.commands.check_database_role import (
    DatabaseRoleAttributes,
)


def test_database_role_check_accepts_least_privileged_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role = DatabaseRoleAttributes(
        name="saas_core_app",
        superuser=False,
        create_database=False,
        create_role=False,
        replication=False,
        bypass_rls=False,
    )
    monkeypatch.setattr(check_database_role, "current_database_role", lambda: role)
    output = StringIO()

    call_command("check_database_role", stdout=output)

    assert "egzekwuje kontrakt RLS" in output.getvalue()


@pytest.mark.parametrize(
    "attribute",
    ["superuser", "create_database", "create_role", "replication", "bypass_rls"],
)
def test_database_role_check_rejects_privileged_role(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
) -> None:
    values = {
        "name": "unsafe_app",
        "superuser": False,
        "create_database": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }
    values[attribute] = True
    role = DatabaseRoleAttributes(**values)  # type: ignore[arg-type]
    monkeypatch.setattr(check_database_role, "current_database_role", lambda: role)

    with pytest.raises(CommandError, match="niedozwolone atrybuty"):
        call_command("check_database_role")
