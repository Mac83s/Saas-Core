"""The connector contract, checked by the server's own validator (W9.6.0).

The fixtures in ``packages/contracts/content-operations`` are the shared
artefact: SeoContentRank validates them with Ajv, SaaS Core validates the very
same files with ``jsonschema``. Two validators over one fixture set is what
stops the contract quietly forking into "what the sender believes" and "what
the receiver accepts" — a fork nobody notices until a change set is refused in
production for a reason neither side can reproduce.

Nothing here reads the directory at runtime yet; the Content Operations API
(W9.6.6) is what will. When it does, the directory has to be copied into the
image, pointed at by an environment variable and covered by a Django system
check, exactly like the site-block and page-template contracts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from jsonschema import Draft202012Validator

CONTRACT_PATH = Path(settings.SITE_BLOCK_CONTRACTS_PATH).parent / "content-operations"


def _read(relative: str) -> Any:
    return json.loads((CONTRACT_PATH / relative).read_text(encoding="utf-8"))


def _change_set_validator() -> Draft202012Validator:
    schema = _read("content-change-set.v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _fixture_index() -> dict[str, Any]:
    return _read("fixtures/index.json")


def test_the_manifest_matches_the_vocabulary_the_server_implements() -> None:
    """The enums in the contract are the frozen vocabulary. If the server's own
    choices drift from them, the contract is describing a different product."""
    from saas_core.modules.shared.sites.capabilities import (
        CONTENT_CONTRACT_VERSION,
        MINIMUM_CONTENT_CONTRACT_VERSION,
    )
    from saas_core.modules.shared.sites.models import (
        AutomationGrantMode,
        PageAutomationPolicy,
        PageType,
    )

    manifest = _read("manifest.json")

    assert manifest["contractVersion"] == CONTENT_CONTRACT_VERSION
    assert manifest["minimumContractVersion"] == MINIMUM_CONTENT_CONTRACT_VERSION
    assert manifest["grantModes"] == [value for value, _ in AutomationGrantMode.choices]
    assert manifest["automationPolicies"] == [
        value for value, _ in PageAutomationPolicy.choices
    ]

    schema = _read("content-change-set.v1.schema.json")
    page_types = schema["$defs"]["commandPageCreate"]["properties"]["page_type"]["enum"]
    assert page_types == [value for value, _ in PageType.choices]

    # ADR-035 §4: the historical name is not an alias, in either direction.
    assert "auto_publish_limited" in manifest["rejectedValues"]
    assert "auto_publish_limited" not in manifest["grantModes"]


def test_accepted_fixtures_pass_the_server_validator() -> None:
    validator = _change_set_validator()
    index = _fixture_index()
    files = sorted(path.name for path in (CONTRACT_PATH / "fixtures/accepted").iterdir())

    assert files == sorted(index["accepted"])
    for name in files:
        errors = list(validator.iter_errors(_read(f"fixtures/accepted/{name}")))
        assert errors == [], f"{name}: {[error.message for error in errors]}"


def test_rejected_fixtures_are_refused_by_the_validator_that_owns_the_rule() -> None:
    from saas_core.modules.shared.sites.block_contracts import (
        InvalidSiteBlockData,
        validate_site_block,
    )

    validator = _change_set_validator()
    index = _fixture_index()
    files = sorted(path.name for path in (CONTRACT_PATH / "fixtures/rejected").iterdir())
    assert files == sorted(index["rejected"])

    for name in files:
        fixture = _read(f"fixtures/rejected/{name}")
        envelope_errors = list(validator.iter_errors(fixture))
        if index["rejected"][name]["by"] == "envelope":
            assert envelope_errors != [], f"{name} should not validate"
            continue

        # The envelope deliberately leaves block payloads to the canonical block
        # schema. This fixture is what proves the second stage actually runs.
        assert envelope_errors == [], f"{name}: {envelope_errors}"
        blocks = [
            command["block"] for command in fixture["commands"] if "block" in command
        ]
        assert blocks
        for block in blocks:
            with pytest.raises(InvalidSiteBlockData):
                validate_site_block(
                    block_type=block["type"],
                    schema_version=block["schema_version"],
                    data=block["data"],
                )


def test_the_contract_offers_no_way_to_move_a_published_address() -> None:
    """`change_page_url` refuses automation outright. A field here would be an
    invitation to a request that can only ever be answered with 403."""
    schema = _read("content-change-set.v1.schema.json")
    fields = schema["$defs"]["commandTranslationUpdate"]["properties"]["fields"]
    assert sorted(fields["properties"]) == [
        "description",
        "social_description",
        "social_title",
        "title",
    ]
    assert fields["additionalProperties"] is False
