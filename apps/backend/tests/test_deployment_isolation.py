"""What has to be separate when two products share a host.

One repository builds several products, and the moment two of them stand next
to each other the question is no longer "does it boot" but "whose database is
this". The answer lives in `compose.yaml` as a set of overridable names; this
keeps the written list and the real one from drifting apart, because a document
nobody checks stops being true at the first change.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

REPOSITORY = Path(settings.BASE_DIR).parent.parent
COMPOSE = REPOSITORY / "compose.yaml"
DOCUMENT = REPOSITORY / "docs" / "operations" / "deployment-matrix.md"

#: The section of the document that lists per-deployment resources. Only that
#: table is read: the release-record table above it mentions other variables in
#: prose, and picking those up would make the check argue with itself.
SECTION = "## 4. Co musi być osobne dla każdego deploymentu"

#: Variables compose parameterises that are the same for every deployment on a
#: host — timeouts, limits and provider switches. They are configuration, not
#: separation, so the isolation table does not carry them.
SHARED_KNOBS = frozenset(
    {
        "BILLING_INVOICE_ADAPTER",
        "BILLING_LIFECYCLE_MAX_ATTEMPTS",
        "BILLING_LIFECYCLE_WARNING_LEAD_SECONDS",
        "BILLING_PROVIDER",
        "BILLING_RECONCILIATION_BATCH_SIZE",
        "BILLING_RECONCILIATION_INTERVAL_SECONDS",
        "BILLING_RECONCILIATION_MAX_ATTEMPTS",
        "CLAMAV_HOST",
        "CLAMAV_PORT",
        "CLAMAV_TIMEOUT_SECONDS",
        "MEDIA_MAX_IMAGE_PIXELS",
        "MEDIA_PROCESSING_RESERVATION_TTL_SECONDS",
        "NOTIFICATIONS_EXPORT_MAX_ROWS",
        "NOTIFICATIONS_EXPORT_TTL_HOURS",
        "NOTIFICATIONS_RETENTION_DAYS",
        "NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS",
        "ORGANIZATION_INVITATION_TTL_SECONDS",
        "SESSION_IDLE_TIMEOUT_SECONDS",
        "SESSION_MAX_LIFETIME_SECONDS",
        "STRIPE_API_VERSION",
        "STRIPE_LIVEMODE",
        "STRIPE_PORTAL_CONFIGURATION_ID",
        "TENANT_TASK_CONTEXT_TTL_SECONDS",
        "TRUSTED_PROXY_COUNT",
    }
)


def compose_variables() -> set[str]:
    """Every name compose lets the environment override.

    A doubled `$$` is an escape for the shell inside a container, not a compose
    substitution, so it is skipped — otherwise a healthcheck's own variables
    would look like deployment configuration.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)(?::-[^}]*)?\}", text)
    }


def documented_variables() -> set[str]:
    text = DOCUMENT.read_text(encoding="utf-8")
    section = text.split(SECTION, 1)
    assert len(section) == 2, f"Brak sekcji {SECTION!r} w {DOCUMENT.name}"
    body = section[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        # Only the variable column. The reason column mentions other names in
        # backticks — a role attribute, for instance — and reading those would
        # have the check argue with prose.
        if len(cells) > 2:
            names.update(re.findall(r"`([A-Z][A-Z0-9_]*)`", cells[2]))
    return names


def test_every_documented_resource_is_actually_overridable() -> None:
    """A row promising separation that compose hardcodes is worse than no row."""
    missing = sorted(documented_variables() - compose_variables())

    assert missing == [], (
        "Dokument obiecuje rozdzielenie, którego compose nie daje. "
        f"Sparametryzuj albo usuń wiersz: {missing}"
    )


def test_every_per_deployment_knob_is_written_down() -> None:
    """The other direction: a new resource nobody documented is a collision."""
    undocumented = sorted(
        variable
        for variable in compose_variables() - documented_variables() - SHARED_KNOBS
        if variable.startswith(("SAAS_CORE_", "OBJECT_STORAGE_", "SESSION_COOKIE"))
        or variable == "DEPLOYMENT"
    )

    assert undocumented == [], (
        "Zmienna rozdzielająca deploymenty bez wiersza w docs/operations/"
        f"deployment-matrix.md: {undocumented}"
    )


def test_the_shared_list_names_only_variables_that_still_exist() -> None:
    stale = sorted(SHARED_KNOBS - compose_variables())

    assert stale == [], f"Compose już ich nie używa, usuń z listy: {stale}"
