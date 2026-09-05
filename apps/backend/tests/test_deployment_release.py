"""Rollback is a fact about the migrations, not a hope about the deploy.

Several products update independently from one repository, so "can this go
back" has to be answerable before it is needed. The answer is mechanical: a
migration is walkable backwards or it is not, and the first one that is not
takes rollback away from every deployment past it — quietly, because nothing
fails until somebody tries.
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.migrations.loader import MigrationLoader

#: Migrations this repository knowingly cannot undo, with the reason. Empty,
#: and it should stay that way: an entry here is a point past which no
#: deployment can be rolled back, so it belongs in a review, not in a commit
#: that happens to add a RunPython without a reverse.
KNOWN_IRREVERSIBLE: dict[str, str] = {}

pytestmark = pytest.mark.django_db


def _irreversible() -> dict[str, str]:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    found: dict[str, str] = {}
    for (app_label, name), migration in sorted(loader.disk_migrations.items()):
        for index, operation in enumerate(migration.operations):
            if not operation.reversible:
                found[f"{app_label}.{name}"] = f"{type(operation).__name__}[{index}]"
    return found


def test_every_migration_can_be_walked_backwards() -> None:
    """Reversible is not the same as harmless — it is the part a deploy can use.

    Undoing a data migration restores the shape of the rows, not the rows it
    dropped. What this asserts is narrower and checkable: the schema can be
    walked back at all, so a rollback is a decision rather than a rescue.
    """
    unexpected = {
        migration: operation
        for migration, operation in _irreversible().items()
        if migration not in KNOWN_IRREVERSIBLE
    }

    assert unexpected == {}, (
        "Migracja bez odwrotności odbiera rollback każdemu deploymentowi za nią. "
        f"Dopisz odwrotność albo wpis do KNOWN_IRREVERSIBLE z powodem: {unexpected}"
    )


def test_the_known_list_only_holds_migrations_that_are_still_irreversible() -> None:
    """A list that keeps entries it no longer needs stops being read."""
    stale = sorted(set(KNOWN_IRREVERSIBLE) - set(_irreversible()))

    assert stale == [], f"Te migracje są już odwracalne, usuń je z listy: {stale}"


def test_the_release_record_says_what_this_image_is_and_where_it_stands() -> None:
    output = StringIO()
    call_command("deployment_release", "--image", "backend=sha256:abc", stdout=output)
    record = json.loads(output.getvalue())

    assert record["deployment"] == "business"
    assert record["profileHash"].startswith("sha256:")
    assert record["images"] == {"backend": "sha256:abc"}
    assert record["rollback"] == {"reversible": True, "irreversible": []}
    # The suite migrates its database, so nothing is pending against it.
    assert record["migrations"]["applied"] is not None
    assert record["migrations"]["pending"] == []
    assert record["migrations"]["shipped"]["organizations"].startswith("0028_")


def test_an_image_digest_without_a_name_is_refused() -> None:
    with pytest.raises(CommandError, match="NAZWA=DIGEST"):
        call_command("deployment_release", "--image", "sha256:abc")
