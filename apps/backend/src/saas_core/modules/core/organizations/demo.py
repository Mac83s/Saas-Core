"""Demo data for a staging stack: `manage.py seed_demo` (Maciej, 30.09).

After logging in to a staging stack there should already be a company with its
team, visits in the calendar and a warehouse with stock, the same as a local
stack after its seed. Core seeds what it owns — the accounts, the
organizations and who is in them with which role — and then asks every composed
module for its part through a registry, the way erasure asks for its checks:
core never imports a shared module, and a product replaces the default scenario
from its own vertical module (ADR-049).

Everything is idempotent. A second run finds what the first one made (an
organization by slug, an account by e-mail, a document by a stable id, a visit
by its idempotency key) and adds only what is new, such as the visits of a day
that was not "today" last time. Nothing is ever deleted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from saas_core.modules.core.identity.models import User, UserStatus

from .audit import record_audit
from .context import activate_tenant_context, context_from_membership, set_local_organization_id
from .models import (
    BillingProfile,
    Membership,
    MembershipStatus,
    Organization,
    OrganizationAuditAction,
    WorkspaceKind,
)
from .pre_tenant import PRE_TENANT_DB
from .role_catalog import system_role

#: Every demo account lives here, so no message can reach a real mailbox.
DEMO_EMAIL_SUFFIX = ".test"
_NAMESPACE = uuid.UUID("5f0c7c1e-3b1d-4d5e-9a2f-0d6e7c1b9a30")


@dataclass(frozen=True)
class DemoPerson:
    email: str
    first_name: str
    last_name: str
    #: A system role key of the organization's type: owner, manager, staff…
    role: str = "owner"


@dataclass(frozen=True)
class DemoOrganization:
    #: How the scenario and the modules' data refer to it.
    key: str
    name: str
    slug: str
    owner: DemoPerson
    members: tuple[DemoPerson, ...] = ()
    #: Empty: the profile's first organization type.
    organization_type: str = ""
    #: The plan the demo uses; billing gives it without a payment.
    plan: str = "pro"
    #: Each module's own data, under its part's name (`booking`, `inventory`…).
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoScenario:
    organizations: tuple[DemoOrganization, ...]
    #: Data between organizations (a farm linked to a company…), by part name.
    data: Mapping[str, Any] = field(default_factory=dict)
    #: The core's own Business scenario: modules fill in their default data.
    default: bool = False


def default_scenario() -> DemoScenario:
    """Business: one studio, its owner, a manager and a member of staff — the
    same people as the local stack's accounts (KONTA-TESTOWE.md)."""
    return DemoScenario(
        organizations=(
            DemoOrganization(
                key="firma",
                name="Studio Testowe",
                slug="studio-testowe",
                owner=DemoPerson("wlasciciel@saas.test", "Anna", "Właścicielka"),
                members=(
                    DemoPerson("kierownik@saas.test", "Marek", "Kierownik", "manager"),
                    DemoPerson("pracownik@saas.test", "Paweł", "Pracownik", "staff"),
                ),
            ),
        ),
        default=True,
    )


DemoPart = Callable[["DemoRun"], None]
_scenario: Callable[[], DemoScenario] = default_scenario
_parts: dict[str, tuple[int, DemoPart]] = {}


def register_demo_scenario(factory: Callable[[], DemoScenario]) -> None:
    """A product's vertical module replaces the Business scenario (last wins:
    verticals are ready after the shared modules)."""
    global _scenario
    _scenario = factory


def register_demo_part(name: str, part: DemoPart, *, order: int) -> None:
    """A module's share of the demo, run in `order` after the organizations exist."""
    _parts[name] = (order, part)


def demo_scenario() -> DemoScenario:
    return _scenario()


def demo_parts() -> list[tuple[str, DemoPart]]:
    return [(name, part) for name, (_order, part) in sorted(_parts.items(), key=lambda i: i[1][0])]


class DemoRequest(HttpRequest):
    """What services that take a request read from it: who acts."""

    def __init__(self, user: User) -> None:
        super().__init__()
        self.user = user
        self.META["REMOTE_ADDR"] = "127.0.0.1"


class DemoRun:
    """One run of the seed: the scenario, what exists, and how to act in it."""

    def __init__(
        self,
        scenario: DemoScenario,
        *,
        password: str,
        log: Callable[[str], None],
        now: datetime | None = None,
    ) -> None:
        self.scenario = scenario
        self.password = password
        self.log = log
        self.now = now or timezone.now()
        self.organizations: dict[str, Organization] = {}
        self.users: dict[str, User] = {}

    # --- lookups ---------------------------------------------------------------

    def spec(self, key: str) -> DemoOrganization:
        return next(item for item in self.scenario.organizations if item.key == key)

    def data(self, key: str, part: str) -> Any:
        return self.spec(key).data.get(part)

    def user(self, email: str) -> User:
        return self.users[email.lower()]

    def stable_id(self, *parts: str) -> uuid.UUID:
        """The same id on every run, so a retried write finds its first result."""
        return uuid.uuid5(_NAMESPACE, "|".join(parts))

    def zone(self, key: str) -> ZoneInfo:
        return ZoneInfo(self.organizations[key].timezone)

    def day(self, key: str, offset: int) -> date:
        return self.now.astimezone(self.zone(key)).date() + timedelta(days=offset)

    def at(self, key: str, offset: int, clock: str) -> datetime:
        hours, minutes = (int(part) for part in clock.split(":"))
        return datetime.combine(self.day(key, offset), time(hours, minutes), tzinfo=self.zone(key))

    # --- acting ----------------------------------------------------------------

    @contextmanager
    def acting(self, key: str, email: str | None = None) -> Iterator[DemoRequest]:
        """Inside the organization as one of its people, in one transaction,
        with the same tenant context a request of theirs would carry."""
        organization = self.organizations[key]
        user = self.user(email or self.spec(key).owner.email)
        with transaction.atomic():
            set_local_organization_id(organization.id)
            membership = Membership.objects.select_related("role").get(
                organization=organization, user=user, status=MembershipStatus.ACTIVE
            )
            with activate_tenant_context(context_from_membership(membership)):
                yield DemoRequest(user)

    # --- core's own part -------------------------------------------------------

    def seed_people_and_organizations(self) -> None:
        for spec in self.scenario.organizations:
            owner = self._account(spec.owner)
            organization = self._organization(spec, owner)
            self.organizations[spec.key] = organization
            for person in spec.members:
                self._membership(organization, self._account(person), person.role)

    def _account(self, person: DemoPerson) -> User:
        email = User.objects.normalize_email(person.email).lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email, self.password, status=UserStatus.ACTIVE)
            self.log(f"+ konto {email}")
        else:
            # An operator's or a switched-off account is never a demo account,
            # whatever its address: the seed does not reset it.
            if user.is_staff or user.is_superuser or user.status != UserStatus.ACTIVE:
                raise ValueError(
                    f"Konto {email} nie jest kontem demo (operator albo wyłączone); "
                    "dane demo go nie zmienią."
                )
            # Demo accounts only (.test): the password is the one given now.
            user.set_password(self.password)
        user.first_name, user.last_name = person.first_name, person.last_name
        user.save()
        self.users[email] = user
        return user

    def _organization(self, spec: DemoOrganization, owner: User) -> Organization:
        found = Organization.objects.using(PRE_TENANT_DB).filter(slug=spec.slug).first()
        if found is not None:
            # A slug is not a claim: the seed goes on only with an organization
            # its own scenario's owner owns, never takes over somebody else's.
            with transaction.atomic():
                set_local_organization_id(found.id)
                owned = Membership.objects.filter(
                    organization=found, user=owner, role__key="owner"
                ).exists()
            if not owned:
                raise ValueError(
                    f"Organizacja {spec.slug} należy do kogoś innego niż {owner.email}; "
                    "dane demo jej nie przejmą."
                )
            self.log(f"= organizacja {spec.name}")
            return found
        organization_type = spec.organization_type or str(settings.DEFAULT_ORGANIZATION_TYPE)
        organization = Organization(
            name=spec.name,
            slug=spec.slug,
            workspace_kind=WorkspaceKind.BUSINESS,
            organization_type=organization_type,
            default_locale="pl",
            timezone="Europe/Warsaw",
            currency="PLN",
        )
        organization.full_clean(validate_unique=False)
        with transaction.atomic():
            set_local_organization_id(organization.id)
            organization.save()
            BillingProfile.objects.create(organization=organization)
            Membership.objects.create(
                organization=organization,
                user=owner,
                role=system_role(organization_type, "owner"),
            )
            record_audit(
                organization=organization,
                action=OrganizationAuditAction.ORGANIZATION_CREATED,
                actor=owner,
                target_type="organization",
                target_id=organization.id,
                metadata={"source": "seed_demo"},
            )
        self.log(f"+ organizacja {spec.name} ({organization_type})")
        return organization

    def _membership(self, organization: Organization, user: User, role_key: str) -> None:
        with transaction.atomic():
            set_local_organization_id(organization.id)
            membership = Membership.objects.filter(organization=organization, user=user).first()
            if membership is not None:
                return
            Membership.objects.create(
                organization=organization,
                user=user,
                role=system_role(organization.organization_type, role_key),
            )
        self.log(f"+ {user.email} w {organization.name} jako {role_key}")


def assert_demo_emails(scenario: DemoScenario) -> None:
    """A demo account never has a real address: no message can reach anybody."""
    for spec in scenario.organizations:
        for person in (spec.owner, *spec.members):
            if not person.email.lower().endswith(DEMO_EMAIL_SUFFIX):
                raise ValueError(f"Konto demo {person.email} musi mieć adres w domenie .test.")


def run_demo(*, password: str, log: Callable[[str], None], now: datetime | None = None) -> DemoRun:
    scenario = demo_scenario()
    assert_demo_emails(scenario)
    run = DemoRun(scenario, password=password, log=log, now=now)
    run.seed_people_and_organizations()
    for name, part in demo_parts():
        log(f"— {name}")
        part(run)
    return run
